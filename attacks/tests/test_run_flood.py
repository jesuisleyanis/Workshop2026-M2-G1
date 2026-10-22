"""run.sh service_flood contre un faux payment-api local : jeton + ids entiers (contrat I8).

Nécessite bash et curl (Git Bash sous Windows) ; sauté sinon.
"""

import json
import os
import shutil
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

RUN_SH = Path(__file__).resolve().parents[1] / "run.sh"
ACCOUNTS = {"demo01": 11, "demo02": 22}
SEED = "seed-pass-test"  # mot de passe FACTICE du jeu de test (SEED_PASSWORD)


def _bash() -> str | None:
    if sys.platform == "win32":  # pas le bash.exe de WSL (System32) : celui de Git
        git = shutil.which("git")  # Git\cmd\git.exe ou Git\mingw64\bin\git.exe
        for parent in Path(git).resolve().parents if git else ():
            if (parent / "bin" / "bash.exe").exists():
                return str(parent / "bin" / "bash.exe")
        return None
    return shutil.which("bash")


BASH = _bash()
pytestmark = pytest.mark.skipif(not BASH, reason="bash/curl indisponibles")


@pytest.fixture
def server():
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            token = (self.headers.get("Authorization") or "").removeprefix("Bearer tok-")
            if token not in ACCOUNTS:
                return self._send(401, {"error": "missing_token"})
            self._send(200, [{"id": ACCOUNTS[token], "iban_fake": "FR-FAKE", "balance_cents": 1,
                              "currency": "EUR"}])

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)))
            if self.path == "/api/v1/login":
                ok = body["username"] in ACCOUNTS and body["password"] == SEED
                return self._send(200 if ok else 401, {"access_token": f"tok-{body['username']}",
                                                       "token_type": "bearer", "expires_in": 900}
                                  if ok else {"error": "invalid_credentials"})
            seen.append((self.headers.get("Authorization"), body))
            self._send(201, {"status": "created"})

        def _send(self, status, payload):
            data = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}", seen
    srv.shutdown()
    srv.server_close()


def _run(target, tmp_path, **env):
    env = {**os.environ, "SEED_PASSWORD": SEED, "RUNLOG": (tmp_path / "runlog").as_posix(),
           "PIDFILE": (tmp_path / "pid").as_posix(), **env}
    return subprocess.run([BASH, RUN_SH.as_posix(), "service_flood", "--target", target,
                           "--duration", "2", "--rate", "10"],
                          env=env, capture_output=True, text=True, timeout=60)


def test_flood_posts_authenticated_integer_ids(server, tmp_path):
    url, seen = server
    res = _run(url, tmp_path)
    assert res.returncode == 0, res.stdout + res.stderr
    assert seen, "aucun POST /api/v1/transactions"
    for auth, body in seen:
        assert auth == "Bearer tok-demo01"
        assert body == {"src_account": 11, "dst_account": 22, "amount_cents": 1}


def test_flood_dst_id_override(server, tmp_path):
    url, seen = server
    assert _run(url, tmp_path, FLOOD_DST_ID="33").returncode == 0
    assert seen and all(body["dst_account"] == 33 for _, body in seen)


def test_flood_aborts_without_valid_session(server, tmp_path):
    url, seen = server
    res = _run(url, tmp_path, FLOOD_PASSWORD="faux")
    assert res.returncode == 1
    assert "make seed" in res.stdout
    assert not seen  # jamais de flood non authentifié (401) ni d'ids manquants (422)


def test_flood_refuses_to_run_without_seed_password(server, tmp_path):
    # Jamais de mot de passe en dur : sans SEED_PASSWORD, le flood s'arrête net (pas de rafale de 401).
    url, seen = server
    res = _run(url, tmp_path, SEED_PASSWORD="")
    assert res.returncode == 1 and "SEED_PASSWORD absent" in res.stdout
    assert not seen
