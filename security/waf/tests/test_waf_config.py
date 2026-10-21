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
    assert re.search(r"upstream\s+payment_api\s*\{[^}]*server\s+payment-api:8001\b", conf)
    assert re.search(r"upstream\s+auth_api\s*\{\s*server\s+auth:8002;", conf)


def test_only_public_routes_are_proxied():
    locations = re.findall(r"location\s+(?:=\s*)?(\S+)\s*\{", _directives(NGINX))
    assert set(locations) == {"/healthz", "/", "/api/v1/accounts", "/api/v1/transactions",
                              "/api/v1/login", "/api/v1/register", "/api/v1/auth/"}
    for forbidden in ("/internal", "/metrics", "remediation", "dashboard:"):
        assert forbidden not in _directives(NGINX), f"{forbidden} ne doit jamais être routé par le WAF"


# --------------------------------------------------------------------------- #6 Dockerfile / non-root / TLS
def test_dockerfile_is_pinned_owasp_crs_nginx_and_non_root():
    assert re.search(r"^FROM owasp/modsecurity-crs:\d+\.\d+\.\d+-nginx-alpine\S*@sha256:[0-9a-f]{64}$", DOCKERFILE, re.M), (
        "image CRS épinglée par tag ET digest (un tag peut être republié, R5)"
    )
    assert re.search(r"^USER nginx\s*$", DOCKERFILE, re.M), "le WAF tourne en utilisateur non-root"
    assert "ENTRYPOINT" not in DOCKERFILE and "CMD [" not in DOCKERFILE, "l'entrypoint de l'image (ModSec/CRS) doit rester actif"


def test_entrypoint_scripts_patching_the_removed_default_conf_are_dropped():
    # conf.d/default.conf est supprimé (nginx.conf du projet fait foi) : les scripts de l'image qui le
    # modifient sous `set -e` (93 PROXY_SSL, 96 HTTP3) feraient échouer le démarrage du WAF.
    assert "/etc/nginx/conf.d/*.conf" in DOCKERFILE
    for script in ("93-update-proxy-ssl-config.sh", "96-update-http3-config.sh"):
        removed = [line for line in DOCKERFILE.splitlines() if "rm -f" in line and f"/docker-entrypoint.d/{script}" in line]
        assert removed, f"{script} doit être retiré de l'image"


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
    assert waf["ports"] == ["80:8080", "443:8443"]
    # Deny-list : volume nommé partagé avec le moteur (jamais un bind-mount de fichier : rename impossible).
    assert "waf-deny:/etc/nginx/deny:rw" in waf["volumes"]
    assert "waf-deny:/etc/resilience/waf-deny:rw" in services["remediation"]["volumes"]
    assert waf["build"] == {"context": "../../security/waf"}
    test = waf["healthcheck"]["test"]
    assert test[0] == "CMD-SHELL" and "8443/healthz" in test[1], "healthcheck exec-form malformé (ticket #10)"
    assert all("ports" not in svc for name, svc in services.items() if name not in {"waf", "mosquitto"}), "seuls WAF et MQTT publient des ports"
    assert services["mosquitto"]["ports"] == ["192.168.137.1:1883:1883"]


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


def test_api_routes_are_rate_limited_by_the_waf():
    # Protection préventive de la disponibilité, indépendante de l'IP (masquée sous Docker Desktop).
    conf = _directives(NGINX)
    assert re.search(r"limit_req_zone \$binary_remote_addr zone=api:\d+m rate=\d+r/s;", conf)
    assert "limit_req_status 429;" in conf
    for route in ("/api/v1/accounts", "/api/v1/transactions", "/api/v1/login", "/api/v1/register", "/api/v1/auth/"):
        line = next(ln for ln in NGINX.splitlines() if f"location {route}" in ln)
        assert "limit_req zone=api" in line, route
    # /healthz (sonde du WAF) n'est jamais limitée
    assert "limit_req" not in next(ln for ln in NGINX.splitlines() if "location = /healthz" in ln)


def test_payment_api_replicas_are_load_balanced_with_failover_but_no_post_replay():
    conf = _directives(NGINX)
    block = re.search(r"upstream\s+payment_api\s*\{([^}]*)\}", conf).group(1)
    assert "least_conn;" in block and "zone payment_api" in block
    # `resolve` : nouvelles IP des répliques (restart, scale) suivies sans recharger nginx
    assert re.search(r"server payment-api:8001 resolve max_fails=\d+ fail_timeout=\d+s;", block)
    assert re.search(r"resolver 127\.0\.0\.11 ", conf)
    for route in ("/api/v1/accounts", "/api/v1/transactions"):
        line = next(ln for ln in NGINX.splitlines() if f"location {route}" in ln)
        assert "proxy_next_upstream error timeout http_502 http_503;" in line, route
        assert "non_idempotent" not in line, "un virement (POST) ne doit jamais être rejoué en double"
