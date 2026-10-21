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
    locations = re.findall(r"location\s+(?:[=~]\s*)?(\S+)\s*\{", _directives(NGINX))
    assert set(locations) == {"/healthz", "/", "/api/v1/accounts", "/api/v1/transactions",
                              "/api/v1/status", "/api/v1/beneficiaries", "/api/v1/stats/spending",
                              "^/api/v1/transactions/[0-9]+$", "/api/v1/limits", "/api/v1/cards", "/api/v1/scheduled-transfers",
                              "/api/v1/notifications",
                              "/api/v1/login", "/api/v1/register", "/api/v1/auth/"}
    for forbidden in ("/internal", "/metrics", "remediation", "dashboard:"):
        assert forbidden not in _directives(NGINX), f"{forbidden} ne doit jamais être routé par le WAF"


def test_crs_allows_delete_and_patch_but_not_put():
    # #43 : DELETE /api/v1/beneficiaries/{id}. Sans ALLOWED_METHODS, la règle CRS 911100 le bloque.
    m = re.search(r'ALLOWED_METHODS="([^"]+)"', DOCKERFILE)
    assert m, "ALLOWED_METHODS doit être fixé dans l'image WAF"
    assert set(m.group(1).split()) == {"GET", "HEAD", "POST", "OPTIONS", "DELETE", "PATCH"}


def test_delete_and_patch_are_denied_everywhere_except_their_one_route():
    conf = _directives(NGINX)
    m = re.search(r'map "\$request_method:\$uri" \$method_denied \{\s*default 0;((?:\s*"~[^"]+" 1;)+)\s*\}', conf)
    assert m, "map $method_denied absente"
    assert re.search(r"if \(\$method_denied\)\s*\{\s*return 405;\s*\}", conf)
    rules = [re.compile(r) for r in re.findall(r'"~([^"]+)" 1;', m.group(1))]

    def denied(probe: str) -> bool:
        return any(r.search(probe) for r in rules)

    assert not denied("DELETE:/api/v1/beneficiaries/12")
    assert not denied("PATCH:/api/v1/cards/3")
    assert not denied("PATCH:/api/v1/scheduled-transfers/7") and not denied("DELETE:/api/v1/scheduled-transfers/7")
    assert denied("DELETE:/api/v1/scheduled-transfers") and denied("PATCH:/api/v1/scheduled-transfers/7/x")
    for probe in ("DELETE:/api/v1/beneficiaries", "DELETE:/api/v1/beneficiaries/12/x",
                  "DELETE:/api/v1/accounts", "DELETE:/api/v1/cards/3", "DELETE:/",
                  "PATCH:/api/v1/cards", "PATCH:/api/v1/cards/3/freeze", "PATCH:/api/v1/accounts",
                  "PATCH:/api/v1/beneficiaries/12"):
        assert denied(probe), probe
    assert not denied("GET:/api/v1/accounts") and not denied("POST:/api/v1/cards/3/freeze")


def test_scheduled_transfers_route_is_rate_limited_per_ip():
    conf = _directives(NGINX)
    assert re.search(r"limit_req_zone\s+\$binary_remote_addr\s+zone=schedules_per_ip:\d+m\s+rate=\d+r/m;", conf)
    assert re.search(r"location /api/v1/scheduled-transfers\s+\{\s*limit_req zone=schedules_per_ip", conf)


def test_notifications_route_is_rate_limited_per_ip():
    conf = _directives(NGINX)
    assert re.search(r"limit_req_zone\s+\$binary_remote_addr\s+zone=notifications_per_ip:\d+m\s+rate=\d+r/m;", conf)
    assert re.search(r"location /api/v1/notifications\s+\{\s*limit_req zone=notifications_per_ip", conf)


def test_cards_route_is_rate_limited_per_ip():
    conf = _directives(NGINX)
    assert re.search(r"limit_req_zone\s+\$binary_remote_addr\s+zone=cards_per_ip:\d+m\s+rate=\d+r/m;", conf)
    assert re.search(r"location /api/v1/cards\s+\{\s*limit_req zone=cards_per_ip", conf)


def test_spending_stats_route_is_rate_limited_and_read_only():
    conf = _directives(NGINX)
    assert re.search(r"limit_req_zone\s+\$binary_remote_addr\s+zone=stats_per_ip:\d+m\s+rate=\d+r/m;", conf)
    block = re.search(r"location = /api/v1/stats/spending \{([^}]*\{[^}]*\}[^}]*)\}", conf)
    assert block and "limit_req zone=stats_per_ip" in block.group(1)
    assert re.search(r"limit_except GET\s*\{\s*deny all;\s*\}", block.group(1))


def test_transaction_detail_is_rate_limited_but_transfers_are_not():
    # #45 : GET /api/v1/transactions/{id} (regex, prioritaire sur le préfixe) est borné par IP ;
    # le préfixe (POST de virement, cible de service_flood) reste sans limite côté WAF.
    conf = _directives(NGINX)
    block = re.search(r"location ~ \^/api/v1/transactions/\[0-9\]\+\$ \{([^}]*\{[^}]*\}[^}]*)\}", conf)
    assert block, "location regex du détail absente"
    assert "limit_req zone=tx_detail_per_ip" in block.group(1)
    assert re.search(r"limit_except GET\s*\{\s*deny all;\s*\}", block.group(1))
    assert re.search(r"limit_req_zone\s+\$binary_remote_addr\s+zone=tx_detail_per_ip:\d+m\s+rate=\d+r/m;", conf)
    prefix = re.search(r"location /api/v1/transactions\s+\{([^}]*)\}", conf)
    assert prefix and "limit_req" not in prefix.group(1), "ne pas étouffer service_flood au WAF"


def test_limits_route_is_exact_rate_limited_and_read_only():
    conf = _directives(NGINX)
    assert re.search(r"limit_req_zone\s+\$binary_remote_addr\s+zone=limits_per_ip:\d+m\s+rate=\d+r/m;", conf)
    block = re.search(r"location = /api/v1/limits\s*\{([^}]*\{[^}]*\}[^}]*)\}", conf)
    assert block and "limit_req zone=limits_per_ip" in block.group(1)
    assert re.search(r"limit_except GET\s*\{\s*deny all;\s*\}", block.group(1))


def test_beneficiaries_route_is_rate_limited_per_ip():
    conf = _directives(NGINX)
    assert re.search(r"limit_req_zone\s+\$binary_remote_addr\s+zone=beneficiaries_per_ip:\d+m\s+rate=\d+r/m;", conf)
    assert re.search(r"location /api/v1/beneficiaries \{\s*limit_req zone=beneficiaries_per_ip", conf)


def test_public_status_route_is_exact_rate_limited_and_read_only():
    # #42 : route sans auth -> correspondance exacte (pas de préfixe ouvert sur payment-api),
    # limite par IP, GET seulement.
    conf = _directives(NGINX)
    assert re.search(r"limit_req_zone\s+\$binary_remote_addr\s+zone=status_per_ip:\d+m\s+rate=\d+r/s;", conf)
    block = re.search(r"location = /api/v1/status\s*\{([^}]*\{[^}]*\}[^}]*)\}", conf)
    assert block, "location exacte /api/v1/status absente"
    body = block.group(1)
    assert "limit_req zone=status_per_ip" in body and "proxy_pass http://payment_api;" in body
    assert re.search(r"limit_except GET\s*\{\s*deny all;\s*\}", body)


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
    assert services["mosquitto"]["ports"] == ["${MQTT_BIND_ADDR:-192.168.137.1}:1883:1883"]


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
