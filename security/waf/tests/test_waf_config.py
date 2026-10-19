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


def test_only_public_routes_are_proxied():
    locations = re.findall(r"location\s+(?:=\s*)?(\S+)\s*\{", _directives(NGINX))
    assert set(locations) == {"/healthz", "/", "/api/v1/accounts", "/api/v1/transactions",
                              "/api/v1/login", "/api/v1/register"}
    for forbidden in ("/internal", "/metrics", "remediation", "dashboard:"):
        assert forbidden not in _directives(NGINX), f"{forbidden} ne doit jamais être routé par le WAF"


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
    assert ports == {8080, 8443} and all(p >= 1024 for p in ports), "ports non privilégiés uniquement"
    assert not re.search(r"^\s*user\s+", conf, re.M)


def test_modsecurity_crs_loaded_and_blocklist_included():
    conf = _directives(NGINX)
    assert "load_module modules/ngx_http_modsecurity_module.so;" in conf
    assert "modsecurity on;" in conf
    assert "modsecurity_rules_file /etc/modsecurity.d/setup.conf;" in conf
    assert "include /etc/nginx/blocked_ips.conf;" in conf and "if ($blocked_source) { return 403; }" in conf
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
    assert waf["ports"] == ["80:8080", "443:8443"]
    assert waf["build"] == {"context": "../../security/waf"}
    test = waf["healthcheck"]["test"]
    assert test[0] == "CMD-SHELL" and "8443/healthz" in test[1], "healthcheck exec-form malformé (ticket #10)"
    assert all("ports" not in svc for name, svc in services.items() if name != "waf"), "seul le WAF publie des ports"
