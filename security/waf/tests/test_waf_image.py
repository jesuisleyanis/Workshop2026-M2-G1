"""Le WAF pour de vrai : image construite, nginx + ModSecurity + CRS, backends factices.

Opt-in (build Docker, ~1 min) : WAF_DOCKER_TESTS=1 python -m pytest security/waf/tests/test_waf_image.py
ou `make test-waf`. Sautés si Docker est absent. Aucun service de la plateforme n'est requis :
trois backends factices répondent sous les noms `front`, `payment-api` et `auth`.

Ce qui est prouvé ici, et que les tests de texte (test_nginx_conf.py) ne peuvent pas prouver :
  * la conf rendue par l'entrypoint de l'image est acceptée par nginx (`nginx -t`) ;
  * le CRS bloque (403) et le journal d'audit reçoit le blocage ;
  * une IP écrite dans le DOSSIER monté (par renommage, comme lineinfile) est bloquée après reload ;
  * X-Forwarded-For envoyé par le client est écrasé ; /metrics, /internal/*, /api/inconnu = 404
    sans atteindre un backend ;
  * le journal d'audit est tronqué au seuil, et nginx continue d'y écrire ;
  * l'error_log garde la cause d'un 502 (connect() failed).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

import pytest

WAF_DIR = Path(__file__).resolve().parents[1]
IMAGE = "resilience/waf-test:pytest"
STUB_IMAGE = "python:3.12-slim"

pytestmark = pytest.mark.skipif(
    os.environ.get("WAF_DOCKER_TESTS") != "1" or shutil.which("docker") is None,
    reason="tests Docker du WAF : WAF_DOCKER_TESTS=1 et docker requis",
)

#: Backend factice : répond en JSON ce qu'il a reçu (qui il est, le chemin, X-Forwarded-For).
STUB = """
import json, sys, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

def make(name):
    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            body = json.dumps({"backend": name, "path": self.path,
                               "xff": self.headers.get("X-Forwarded-For"),
                               "real_ip": self.headers.get("X-Real-IP")}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("X-Frame-Options", "SAMEORIGIN")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        do_POST = do_GET
        def log_message(self, *a): pass
    return H

for name, port in (("front", 8080), ("payment-api", 8001), ("auth", 8002)):
    threading.Thread(target=ThreadingHTTPServer(("0.0.0.0", port), make(name)).serve_forever, daemon=True).start()
threading.Event().wait()
"""


def _docker(*args: str, check: bool = True, timeout: int = 180) -> subprocess.CompletedProcess:
    res = subprocess.run(["docker", *args], capture_output=True, text=True, timeout=timeout)
    if check and res.returncode != 0:
        raise AssertionError(f"docker {' '.join(args[:3])} : {res.stderr.strip() or res.stdout.strip()}")
    return res


def _daemon_up() -> bool:
    try:
        return subprocess.run(["docker", "info"], capture_output=True, timeout=20).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


class Waf:
    def __init__(self, name: str, network: str, blocklist_dir: Path):
        self.name, self.network, self.blocklist_dir = name, network, blocklist_dir
        self.port = 0

    def start(self, *env: str) -> None:
        env_args = [a for e in env for a in ("-e", e)]
        _docker(
            "run", "-d", "--name", self.name, "--network", self.network,
            "--cap-drop", "ALL", "--security-opt", "no-new-privileges:true",   # comme le compose
            "-v", f"{self.blocklist_dir}:/etc/nginx/blocklist:ro",
            "--tmpfs", "/var/log/modsec:size=64m,uid=101,gid=101,mode=0750",
            "-p", "127.0.0.1::8080", *env_args, IMAGE,
        )
        self.port = int(_docker("port", self.name, "8080/tcp").stdout.split(":")[-1])
        deadline = time.time() + 60
        while time.time() < deadline:
            try:
                if self.get("/")[0] == 200:
                    return
            except OSError:              # le port est publié avant que nginx n'écoute
                pass
            time.sleep(0.5)
        raise AssertionError("le WAF ne répond pas :\n" + _docker("logs", self.name, check=False).stderr[-2000:])

    def get(self, path: str, headers: dict[str, str] | None = None) -> tuple[int, dict[str, str], str]:
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", headers=headers or {})
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status, dict(resp.headers), resp.read().decode()
        except urllib.error.HTTPError as err:
            return err.code, dict(err.headers), err.read().decode()

    def exec(self, *cmd: str) -> str:
        return _docker("exec", self.name, *cmd).stdout

    def reload(self) -> None:
        self.exec("nginx", "-s", "reload")
        time.sleep(1.5)     # les anciens workers terminent leurs requêtes, les nouveaux lisent la liste


@pytest.fixture(scope="module")
def stack(tmp_path_factory):
    if not _daemon_up():
        pytest.skip("démon Docker injoignable")
    suffix = uuid.uuid4().hex[:8]
    network, stub, waf_name = f"waftest-{suffix}", f"waftest-stub-{suffix}", f"waftest-waf-{suffix}"
    blocklist = tmp_path_factory.mktemp("blocklist")
    (blocklist / "blocked_ips.conf").write_text("# vide\n", encoding="utf-8")
    _docker("build", "-q", "-t", IMAGE, str(WAF_DIR), timeout=600)
    _docker("network", "create", network)
    try:
        _docker("run", "-d", "--name", stub, "--network", network,
                "--network-alias", "front", "--network-alias", "payment-api", "--network-alias", "auth",
                STUB_IMAGE, "python", "-c", STUB)
        waf = Waf(waf_name, network, blocklist)
        waf.start("AUDIT_LOG_MAX_BYTES=1048576", "AUDIT_ROTATE_INTERVAL_S=1")
        yield waf, stub, blocklist
    finally:
        _docker("rm", "-f", waf_name, stub, check=False)
        _docker("network", "rm", network, check=False)


def _audit_lines(waf: Waf) -> list[dict]:
    out = waf.exec("sh", "-c", "cat /var/log/modsec/audit.json 2>/dev/null || true")
    return [json.loads(line) for line in out.splitlines() if line.strip()]


SQLI = "/api/v1/accounts?id=1%27%20OR%20%271%27=%271"


def test_nginx_accepts_the_rendered_configuration(stack):
    waf, _, _ = stack
    waf.exec("nginx", "-t")


def test_legitimate_requests_are_relayed_with_waf_security_headers(stack):
    waf, _, _ = stack
    status, headers, body = waf.get("/")
    assert status == 200 and json.loads(body)["backend"] == "front"
    assert json.loads(waf.get("/api/v1/accounts")[2])["backend"] == "payment-api"
    assert json.loads(waf.get("/api/v1/login")[2])["backend"] == "auth"
    assert headers["X-Frame-Options"] == "DENY"          # celui du WAF, pas le SAMEORIGIN du backend
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert "Server" not in headers or "nginx" not in headers["Server"].lower()


def test_forwarded_for_from_the_client_is_overwritten(stack):
    waf, _, _ = stack
    body = json.loads(waf.get("/", headers={"X-Forwarded-For": "6.6.6.6, 7.7.7.7"})[2])
    assert "6.6.6.6" not in body["xff"] and "," not in body["xff"]
    assert body["xff"] == body["real_ip"]                # l'adresse vue par le WAF, pas celle du client


@pytest.mark.parametrize("path", ["/metrics", "/internal/tighten-rate-limit", "/api/v1/inconnu", "/api/"])
def test_internal_and_undeclared_routes_never_reach_a_backend(stack, path):
    waf, _, _ = stack
    status, _, body = waf.get(path)
    assert status == 404
    assert '"backend"' not in body


def test_healthz_is_not_reachable_from_outside(stack):
    waf, _, _ = stack
    assert waf.get("/healthz")[0] == 404
    assert waf.exec("curl", "-fs", "http://127.0.0.1:8080/healthz").strip() == "OK"


def test_crs_blocks_sqli_and_the_audit_log_records_it(stack):
    waf, _, _ = stack
    before = len(_audit_lines(waf))
    assert waf.get(SQLI)[0] == 403
    deadline = time.time() + 10
    while time.time() < deadline and len(_audit_lines(waf)) == before:
        time.sleep(0.3)
    record = _audit_lines(waf)[-1]["transaction"]
    assert record["response"]["http_code"] == 403
    assert any(m["details"]["ruleId"] == "942100" for m in record["messages"])


def test_audit_log_keeps_no_request_headers(stack):
    waf, _, _ = stack
    waf.get(SQLI, headers={"Authorization": "Bearer TOKEN-ZQ9-SECRET"})
    time.sleep(1)
    raw = waf.exec("sh", "-c", "cat /var/log/modsec/audit.json")
    assert "TOKEN-ZQ9-SECRET" not in raw


def test_ip_written_by_rename_in_the_mounted_directory_is_blocked_after_reload(stack):
    """Le playbook réécrit le fichier par renommage (lineinfile) : le WAF doit voir la nouvelle
    liste parce que c'est le DOSSIER qui est monté."""
    waf, _, blocklist = stack
    source_ip = json.loads(waf.get("/")[2])["real_ip"]
    target, tmp = blocklist / "blocked_ips.conf", blocklist / ".blocked_ips.conf.tmp"

    tmp.write_text(f"{source_ip} 1;\n", encoding="utf-8")
    os.replace(tmp, target)                             # nouvel inode, comme Ansible
    waf.reload()
    assert waf.get("/")[0] == 403
    assert waf.get("/api/v1/accounts")[0] == 403

    tmp.write_text("# vide\n", encoding="utf-8")
    os.replace(tmp, target)
    waf.reload()
    assert waf.get("/")[0] == 200


def test_audit_log_is_truncated_at_the_threshold_and_nginx_keeps_writing(stack):
    waf, _, _ = stack
    # remplit le journal au-dessus du seuil (1 Mio dans ce test), sans passer par le CRS
    waf.exec("sh", "-c", "head -c 1500000 /dev/zero | tr '\\0' 'x' >> /var/log/modsec/audit.json; echo >> /var/log/modsec/audit.json")
    deadline = time.time() + 20
    size = 1_500_000
    while time.time() < deadline and size >= 1_048_576:
        time.sleep(1)
        size = int(waf.exec("stat", "-c", "%s", "/var/log/modsec/audit.json").strip())
    assert size < 1_048_576, "le journal n'a pas été tronqué"
    before = len(_audit_lines(waf))
    assert waf.get(SQLI)[0] == 403
    deadline = time.time() + 10
    while time.time() < deadline and len(_audit_lines(waf)) == before:
        time.sleep(0.3)
    assert json.loads(waf.exec("sh", "-c", "tail -n 1 /var/log/modsec/audit.json"))["transaction"]["response"]["http_code"] == 403


def test_error_log_keeps_the_cause_of_a_502(stack):
    waf, stub, _ = stack
    _docker("stop", stub)
    try:
        status = waf.get("/api/v1/accounts?token=ZQ9SECRET")[0]
        assert status == 502
        time.sleep(0.5)
        logs = _docker("logs", waf.name, check=False)
        stderr = logs.stderr
        # cause visible (niveau error) : sans elle un 502 est inexplicable...
        assert "[error]" in stderr and ("could not be resolved" in stderr or "connect() failed" in stderr)
        # ...et la requête complète y figure bel et bien dans le log local du conteneur : c'est
        # pourquoi Promtail masque les query strings avant Loki (test_nginx_conf.py).
        assert "ZQ9SECRET" in stderr
    finally:
        _docker("start", stub, check=False)
