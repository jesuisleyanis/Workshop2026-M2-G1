"""Contrat de configuration du WAF (vérifiable sans Docker) : Dockerfile, nginx.conf, Compose.

Couvre les régressions des tickets #6 (Dockerfile absent, TLS, non-root) et #7 (upstream front:80
alors que le front écoute :8080). La validation live (build + CRS) se fait avec `make up`.
"""

import re
from pathlib import Path

import pytest

WAF = Path(__file__).resolve().parents[1]
ROOT = WAF.parents[1]
NGINX = (WAF / "nginx.conf").read_text(encoding="utf-8")
DOCKERFILE = (WAF / "Dockerfile").read_text(encoding="utf-8")
COMPOSE = (ROOT / "infra" / "compose" / "docker-compose.yml").read_text(encoding="utf-8")
FRONT_NGINX = (ROOT / "services" / "front" / "docker" / "nginx.conf").read_text(encoding="utf-8")


def _directives(text: str) -> str:
    """Retire les commentaires (# ...) pour ne tester que les directives effectives."""
    return "\n".join(re.sub(r"#.*$", "", line) for line in text.splitlines())


# --------------------------------------------------------------------------- #7 upstreams
def test_front_upstream_matches_front_container_port():
    listen = re.search(r"listen\s+(\d+);", FRONT_NGINX)
    assert listen, "le front doit déclarer un port d'écoute"
    assert re.search(rf"upstream\s+front_app\s*\{{\s*server\s+front:{listen.group(1)};", _directives(NGINX)), (
        f"l'upstream front_app doit cibler front:{listen.group(1)} (port réel du conteneur front)"
    )


def test_api_upstreams_target_service_ports():
    conf = _directives(NGINX)
    assert re.search(r"upstream\s+payment_api\s*\{\s*server\s+payment-api:8001;", conf)
    assert re.search(r"upstream\s+auth_api\s*\{\s*server\s+auth:8002;", conf)


def _servers(text: str) -> list[str]:
    """Découpe les blocs `server { ... }` (accolades équilibrées) du nginx.conf, commentaires retirés."""
    conf = _directives(text)
    blocks, i = [], 0
    while (i := conf.find("server {", i)) != -1:
        depth, j = 0, conf.index("{", i)
        start = j
        while True:
            depth += conf[j] == "{"
            depth -= conf[j] == "}"
            j += 1
            if depth == 0:
                break
        blocks.append(conf[start:j])
        i = j
    return blocks


def _locations(block: str) -> list[str]:
    return re.findall(r"location\s+((?:\^~\s+|=\s+)?\S+)\s*\{", block)


PUBLIC_SERVER = next(b for b in _servers(NGINX) if "listen 8443" in b)
HOST_SERVER = next((b for b in _servers(NGINX) if "listen 9443" in b), "")


def test_only_public_routes_are_proxied():
    assert set(_locations(PUBLIC_SERVER)) == {
        "= /healthz", "/", "/api/v1/accounts", "/api/v1/transactions", "/api/v1/login", "/api/v1/register",
        "^~ /api/v1/auth/", "^~ /api/v1/admin/",
    }
    for forbidden in ("/internal", "/metrics", "remediation", "dashboard:"):
        assert forbidden not in _directives(NGINX), f"{forbidden} ne doit jamais être routé par le WAF"


def test_public_server_returns_404_on_host_only_prefixes():
    for prefix in ("/api/v1/auth/", "/api/v1/admin/"):
        assert re.search(rf"location \^~ {re.escape(prefix)}\s*\{{\s*return 404;\s*\}}", PUBLIC_SERVER), prefix
        assert "auth_api" not in re.search(rf"location \^~ {re.escape(prefix)}\s*\{{[^}}]*\}}", PUBLIC_SERVER).group(0)
    # login / register restent publics.
    assert re.search(r"location /api/v1/login\s*\{[^}]*proxy_pass http://auth_api", PUBLIC_SERVER)
    assert re.search(r"location /api/v1/register\s*\{[^}]*proxy_pass http://auth_api", PUBLIC_SERVER)


def test_backoffice_upstream_targets_backoffice_container():
    assert re.search(r"upstream\s+backoffice_app\s*\{\s*server\s+backoffice:8080;", _directives(NGINX))


def test_modsecurity_body_limits_match_host_client_max_body_size():
    """Les plafonds ModSecurity doivent suivre le 4m du listener hôte, sinon le défaut CRS (~128 Kio) rejette les captures."""
    yaml = pytest.importorskip("yaml")
    env = yaml.safe_load(COMPOSE)["services"]["waf"]["environment"]
    size = re.search(r"client_max_body_size\s+(\d+)m;", HOST_SERVER)
    assert size, "le listener hôte doit déclarer client_max_body_size en Mo"
    expected = int(size.group(1)) * 1024 * 1024
    assert expected == 4194304
    assert int(env["MODSEC_REQ_BODY_LIMIT"]) == expected
    assert int(env["MODSEC_REQ_BODY_NOFILES_LIMIT"]) == expected
    # Le serveur public garde le défaut nginx (1m) : pas de client_max_body_size, donc plafonné par nginx.
    assert "client_max_body_size" not in PUBLIC_SERVER
    # Aucun autre endroit ne surcharge ces limites (Dockerfile / entrypoint).
    assert "MODSEC_REQ_BODY" not in DOCKERFILE
    for script in (WAF / "docker-entrypoint.d").glob("*"):
        assert "MODSEC_REQ_BODY" not in script.read_text(encoding="utf-8")


def test_host_listener_9443_routes_auth_admin_and_backoffice():
    assert re.search(r"listen\s+9443\s+ssl;", HOST_SERVER)
    assert "http2 on;" in HOST_SERVER
    assert re.search(r"ssl_certificate\s+/etc/nginx/conf/server\.crt;", HOST_SERVER)
    assert re.search(r"ssl_certificate_key\s+/etc/nginx/conf/server\.key;", HOST_SERVER)
    assert "ssl_protocols       TLSv1.2 TLSv1.3;" in HOST_SERVER
    assert "if ($blocked_source) { return 403; }" in HOST_SERVER
    assert "client_max_body_size 4m;" in HOST_SERVER
    for header in ("X-Content-Type-Options nosniff", "X-Frame-Options DENY", "Referrer-Policy no-referrer"):
        assert f"add_header {header} always;" in HOST_SERVER
    # Le back-office pose lui-même sa CSP / Permissions-Policy ; le WAF ne doit pas la contredire.
    for m in re.findall(r"add_header\s+Permissions-Policy\s+(.*?);", HOST_SERVER):
        assert "camera=(self)" in m
    assert set(_locations(HOST_SERVER)) == {"= /healthz", "/", "/api/v1/auth/", "/api/v1/admin/"}
    assert re.search(r"location / \{[^}]*proxy_pass http://backoffice_app;", HOST_SERVER)
    for prefix in ("/api/v1/auth/", "/api/v1/admin/"):
        loc = re.search(rf"location {re.escape(prefix)}\s*\{{[^}}]*\}}", HOST_SERVER).group(0)
        assert "proxy_pass http://auth_api;" in loc
        assert "proxy_set_header X-Forwarded-For $remote_addr;" in loc


# --------------------------------------------------------------------------- #6 Dockerfile / non-root / TLS
def test_dockerfile_is_pinned_owasp_crs_nginx_and_non_root():
    assert re.search(r"^FROM owasp/modsecurity-crs:\d+\.\d+\.\d+-nginx-alpine", DOCKERFILE, re.M), "image CRS épinglée"
    assert re.search(r"^USER nginx\s*$", DOCKERFILE, re.M), "le WAF tourne en utilisateur non-root"
    assert "ENTRYPOINT" not in DOCKERFILE and "CMD [" not in DOCKERFILE, "l'entrypoint de l'image (ModSec/CRS) doit rester actif"


def test_tls_certificate_generated_at_build_and_used_by_nginx():
    assert "openssl req -x509" in DOCKERFILE
    key = re.search(r"-keyout\s+(\S+)", DOCKERFILE).group(1)
    crt = re.search(r"-out\s+(\S+)", DOCKERFILE).group(1)
    conf = _directives(NGINX)
    assert f"ssl_certificate     {crt};" in conf or f"ssl_certificate {crt};" in conf
    assert f"ssl_certificate_key {key};" in conf
    assert re.search(r"listen\s+8443\s+ssl;", conf)


def test_nginx_runs_unprivileged():
    conf = _directives(NGINX)
    assert "pid /tmp/nginx.pid;" in conf
    assert "client_body_temp_path /tmp/" in conf and "proxy_temp_path" in conf
    ports = {int(p) for p in re.findall(r"listen\s+(\d+)", conf)}
    assert ports == {8080, 8443, 9443} and all(p >= 1024 for p in ports), "ports non privilégiés uniquement"
    assert not re.search(r"^\s*user\s+", conf, re.M)


def test_modsecurity_crs_loaded_and_blocklist_included():
    conf = _directives(NGINX)
    assert "load_module modules/ngx_http_modsecurity_module.so;" in conf
    assert "modsecurity on;" in conf
    assert "modsecurity_rules_file /etc/modsecurity.d/setup.conf;" in conf
    assert "include /etc/nginx/deny/blocked_ips.conf;" in conf and "if ($blocked_source) { return 403; }" in conf
    # Les templates ModSecurity de l'image doivent rester : ils rendent setup.conf au démarrage.
    removed = re.findall(r"rm -r?f? ?(\S+)", re.sub(r"#.*$", "", DOCKERFILE, flags=re.M))
    assert not any("modsecurity.d" in path for path in removed)


def test_healthz_served_locally():
    assert re.search(r"location = /healthz\s*\{[^}]*return 200", _directives(NGINX), re.S)


# --------------------------------------------------------------------------- Compose
def test_compose_publishes_80_443_to_unprivileged_ports_with_valid_healthcheck():
    yaml = pytest.importorskip("yaml")
    services = yaml.safe_load(COMPOSE)["services"]
    waf = services["waf"]
    assert waf["ports"] == ["80:8080", "443:8443", "127.0.0.1:9443:9443"]
    # Deny-list : volume nommé partagé avec le moteur (jamais un bind-mount de fichier : rename impossible).
    assert "waf-deny:/etc/nginx/deny:rw" in waf["volumes"]
    assert "waf-deny:/etc/resilience/waf-deny:rw" in services["remediation"]["volumes"]
    assert waf["build"] == {"context": "../../security/waf"}
    test = waf["healthcheck"]["test"]
    assert test[0] == "CMD-SHELL" and "8443/healthz" in test[1], "healthcheck exec-form malformé (ticket #10)"
    assert {n for n, svc in services.items() if "ports" in svc} == {"waf", "mosquitto"}, "seuls le WAF (HTTP) et mosquitto (MQTT hotspot) publient des ports"


# --------------------------------------------------------------------------- #12 waf-exporter
EXPORTER_DOCKERFILE = (WAF / "Dockerfile.exporter").read_text(encoding="utf-8")
PROMETHEUS = (ROOT / "infra" / "prometheus" / "prometheus.yml").read_text(encoding="utf-8")


def test_waf_writes_modsec_audit_log_to_the_shared_volume():
    yaml = pytest.importorskip("yaml")
    waf = yaml.safe_load(COMPOSE)["services"]["waf"]
    env = waf["environment"]
    assert env["MODSEC_AUDIT_LOG_FORMAT"] == "JSON" and env["MODSEC_AUDIT_LOG_TYPE"] == "Serial"
    assert env["MODSEC_AUDIT_LOG"].startswith("/var/log/modsec/")
    assert "waf-logs:/var/log/modsec:rw" in waf["volumes"]
    assert re.search(r"mkdir -p /var/log/modsec && chown nginx:nginx /var/log/modsec", DOCKERFILE)


def test_waf_exporter_service_reads_the_audit_log_and_is_scraped():
    yaml = pytest.importorskip("yaml")
    services = yaml.safe_load(COMPOSE)["services"]
    exp = services["waf-exporter"]
    assert exp["build"] == {"context": "../..", "dockerfile": "security/waf/Dockerfile.exporter"}
    assert "waf-logs:/var/log/modsec:ro" in exp["volumes"], "lecture seule du journal"
    assert "ports" not in exp and exp["networks"] == ["obs"], "jamais exposé : scrappé sur obs uniquement"
    assert exp["cap_drop"] == ["ALL"] and exp["read_only"] is True
    assert "9188/metrics" in exp["healthcheck"]["test"][-1]
    targets = yaml.safe_load(PROMETHEUS)["scrape_configs"]
    job = next(j for j in targets if j["job_name"] == "waf-exporter")
    assert job["static_configs"][0]["targets"] == ["waf-exporter:9188"]


def test_waf_exporter_image_is_non_root_and_bundles_shared_lib():
    assert re.search(r"^USER 10006:10006", EXPORTER_DOCKERFILE, re.M)
    assert "libs/python/resilience_common" in EXPORTER_DOCKERFILE
    assert 'CMD ["python", "/app/waf_exporter.py"]' in EXPORTER_DOCKERFILE
