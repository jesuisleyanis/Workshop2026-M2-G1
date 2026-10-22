"""Contrat de configuration du WAF (vérifiable sans Docker) : Dockerfile, nginx.conf, Compose.

Couvre les régressions des tickets #6 (Dockerfile absent, TLS, non-root) et #7 (upstream front:80
alors que le front écoute :8080). La validation live (build + CRS) se fait avec `make up`.
"""

import re
import shutil
import subprocess
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
    return re.findall(r"location\s+((?:\^~\s+|=\s+|~\s+)?\S+)\s*\{", block)


PUBLIC_SERVER = next(b for b in _servers(NGINX) if "listen 8443" in b)
HOST_SERVER = next((b for b in _servers(NGINX) if "listen 9443" in b), "")


def test_only_public_routes_are_proxied():
    assert set(_locations(PUBLIC_SERVER)) == {
        "= /healthz", "/", "/api/v1/accounts", "/api/v1/transactions", "~ ^/api/v1/transactions/[0-9]+$",
        "= /api/v1/status", "/api/v1/beneficiaries", "= /api/v1/stats/spending", "= /api/v1/limits",
        "/api/v1/cards", "/api/v1/scheduled-transfers", "/api/v1/notifications", "= /api/v1/statements",
        "/api/v1/login", "/api/v1/register", "= /api/v1/auth/step-up",
        "^~ /api/v1/auth/", "^~ /api/v1/admin/", "= /metrics",
    }
    # /metrics n'apparaît que comme REFUS explicite (404), jamais comme route vers un service.
    routed = PUBLIC_SERVER.replace("location = /metrics { return 404; }", "")
    for forbidden in ("/internal", "/metrics", "remediation", "dashboard:"):
        assert forbidden not in routed, f"{forbidden} ne doit jamais être routé par le WAF"


def test_public_server_returns_404_on_host_only_prefixes():
    for prefix in ("/api/v1/auth/", "/api/v1/admin/"):
        assert re.search(rf"location \^~ {re.escape(prefix)}\s*\{{\s*return 404;\s*\}}", PUBLIC_SERVER), prefix
        assert "auth_api" not in re.search(rf"location \^~ {re.escape(prefix)}\s*\{{[^}}]*\}}", PUBLIC_SERVER).group(0)
    # Seule route /api/v1/auth/ publique : la ré-authentification du front (#51), en correspondance exacte.
    step_up = re.search(r"location = /api/v1/auth/step-up\s*\{[^}]*\}", PUBLIC_SERVER)
    assert step_up and "proxy_pass http://auth_api;" in step_up.group(0)
    assert not re.search(r"location /api/v1/(auth|admin)/", PUBLIC_SERVER), "aucun préfixe auth/admin proxifié en public"
    # login / register restent publics.
    assert re.search(r"location /api/v1/login\s*\{[^}]*proxy_pass http://auth_api", PUBLIC_SERVER)
    assert re.search(r"location /api/v1/register\s*\{[^}]*proxy_pass http://auth_api", PUBLIC_SERVER)


def test_backoffice_upstream_targets_backoffice_container():
    assert re.search(r"upstream\s+backoffice_app\s*\{\s*server\s+backoffice:8080;", _directives(NGINX))


def test_modsecurity_body_limits_match_host_client_max_body_size():
    """Plafond ModSecurity relevé à 4 Mo UNIQUEMENT sur le listener hôte 9443 (captures faciales).

    Le serveur public 80/443 garde le défaut de l'image CRS (128 Kio hors fichiers) : un corps JSON
    plus gros y est rejeté par ModSecurity (règle 200002, 400) avant d'atteindre auth/payment-api.
    Recette live : POST ~300 Kio sur https://localhost/api/v1/login -> 400 (WAF) ; même taille sur
    https://localhost:9443/api/v1/auth/face -> réponse d'auth (422 de validation), pas du WAF.
    """
    yaml = pytest.importorskip("yaml")
    env = yaml.safe_load(COMPOSE)["services"]["waf"]["environment"]
    size = re.search(r"client_max_body_size\s+(\d+)m;", HOST_SERVER)
    assert size, "le listener hôte doit déclarer client_max_body_size en Mo"
    expected = int(size.group(1)) * 1024 * 1024
    assert expected == 4194304
    # Listener hôte : plafonds ModSecurity alignés sur client_max_body_size (directives du bloc server).
    raised = dict(re.findall(r"modsecurity_rules\s+'(SecRequestBody(?:NoFiles)?Limit)\s+(\d+)';", HOST_SERVER))
    assert {k: int(v) for k, v in raised.items()} == {
        "SecRequestBodyLimit": expected, "SecRequestBodyNoFilesLimit": expected,
    }
    # Serveur public : aucun relèvement, défaut CRS 128 Kio explicite dans le Compose (global).
    assert "modsecurity_rules" not in PUBLIC_SERVER
    assert "client_max_body_size" not in PUBLIC_SERVER
    assert int(env["MODSEC_REQ_BODY_NOFILES_LIMIT"]) == 131072
    assert "MODSEC_REQ_BODY_LIMIT" not in env, "défaut de l'image (12,5 Mo avec fichiers) conservé"
    assert "modsecurity_rules " not in _directives(NGINX).replace(HOST_SERVER, "")
    # Aucun autre endroit ne surcharge ces limites (Dockerfile / entrypoint).
    assert "MODSEC_REQ_BODY" not in DOCKERFILE
    for script in (WAF / "docker-entrypoint.d").glob("*"):
        assert "MODSEC_REQ_BODY" not in script.read_text(encoding="utf-8")


def test_crs_allowed_methods_cover_every_backoffice_api_method():
    """CRS 911100 bloque toute méthode hors `ALLOWED_METHODS` (défaut image : GET HEAD POST OPTIONS).

    Le back-office appelle l'API d'administration en PATCH (rôle), PUT et DELETE (visage) : chaque
    méthode utilisée par services/backoffice/src/api doit être admise, sinon 403 sur 9443.
    """
    yaml = pytest.importorskip("yaml")
    env = yaml.safe_load(COMPOSE)["services"]["waf"]["environment"]
    allowed = set(env["ALLOWED_METHODS"].split())
    api_dir = ROOT / "services" / "backoffice" / "src" / "api"
    used = {"GET"}  # défaut de http.ts (init.method ?? 'GET')
    for src in api_dir.glob("*.ts"):
        if src.name.endswith(".test.ts"):
            continue
        used |= set(re.findall(r"method:\s*'([A-Z]+)'", src.read_text(encoding="utf-8")))
    assert {"POST", "PATCH", "PUT", "DELETE"} <= used, "le scan des clients API a échoué"
    assert used <= allowed, f"méthodes bloquées par le CRS : {sorted(used - allowed)}"
    assert {"HEAD", "OPTIONS"} <= allowed  # défaut CRS conservé (sondes, pré-vols)
    # Le Compose surcharge le défaut de l'image (DELETE/PATCH du front) en y ajoutant ce que le
    # back-office utilise ; PUT reste refusé sur le serveur public par $method_denied (405).
    image = set(re.search(r'ALLOWED_METHODS="([^"]+)"', DOCKERFILE).group(1).split())
    assert image <= allowed
    assert re.search(r"if \(\$method_denied\)\s*\{\s*return 405;\s*\}", PUBLIC_SERVER)
    assert "$method_denied" not in HOST_SERVER, "l'API d'administration (PATCH/PUT/DELETE) passe sur 9443"


def test_host_listener_9443_routes_auth_admin_and_backoffice():
    assert re.search(r"listen\s+9443\s+ssl;", HOST_SERVER)
    assert "http2 on;" in HOST_SERVER
    assert re.search(r"ssl_certificate\s+/etc/nginx/conf/server\.crt;", HOST_SERVER)
    assert re.search(r"ssl_certificate_key\s+/etc/nginx/conf/server\.key;", HOST_SERVER)
    assert "ssl_protocols       TLSv1.2 TLSv1.3;" in HOST_SERVER
    assert "if ($blocked_source) { return 403; }" in HOST_SERVER
    assert "client_max_body_size 4m;" in HOST_SERVER
    for header in ("X-Content-Type-Options nosniff", "X-Frame-Options DENY", "Referrer-Policy no-referrer",
                   'Strict-Transport-Security "max-age=31536000"'):
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
    # PUT (admis par le CRS pour le listener hôte 9443) est refusé partout sur le serveur public.
    for probe in ("PUT:/api/v1/accounts", "PUT:/api/v1/cards/3", "PUT:/api/v1/admin/users/1/face", "PUT:/"):
        assert denied(probe), probe


def test_scheduled_transfers_route_is_rate_limited_per_ip():
    conf = _directives(NGINX)
    assert re.search(r"limit_req_zone\s+\$binary_remote_addr\s+zone=schedules_per_ip:\d+m\s+rate=\d+r/m;", conf)
    assert re.search(r"location /api/v1/scheduled-transfers\s+\{\s*limit_req zone=schedules_per_ip", conf)


def test_notifications_route_is_rate_limited_per_ip():
    conf = _directives(NGINX)
    assert re.search(r"limit_req_zone\s+\$binary_remote_addr\s+zone=notifications_per_ip:\d+m\s+rate=\d+r/m;", conf)
    assert re.search(r"location /api/v1/notifications\s+\{\s*limit_req zone=notifications_per_ip", conf)


def test_statements_route_is_exact_rate_limited_and_read_only():
    conf = _directives(NGINX)
    assert re.search(r"limit_req_zone\s+\$binary_remote_addr\s+zone=statements_per_ip:\d+m\s+rate=\d+r/m;", conf)
    block = re.search(r"location = /api/v1/statements\s*\{([^}]*\{[^}]*\}[^}]*)\}", conf)
    assert block and "limit_req zone=statements_per_ip" in block.group(1)
    assert re.search(r"limit_except GET\s*\{\s*deny all;\s*\}", block.group(1))


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
    # Le virement (POST, cible légitime de service_flood) ne subit PAS la limite par IP du détail :
    # seule la zone globale `api` (écrêtage préventif large, 30 r/s) s'y applique.
    assert prefix and "tx_detail_per_ip" not in prefix.group(1), "ne pas étouffer service_flood au WAF"


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


def test_modsec_audit_log_is_bounded_by_a_background_rotation():
    yaml = pytest.importorskip("yaml")
    env = yaml.safe_load(COMPOSE)["services"]["waf"]["environment"]
    assert int(env["WAF_AUDIT_MAX_BYTES"]) > 0
    assert "audit-log-rotate.sh /usr/local/bin/audit-log-rotate.sh" in DOCKERFILE
    assert "07-audit-log-rotate.sh /docker-entrypoint.d/07-audit-log-rotate.sh" in DOCKERFILE
    launcher = (WAF / "docker-entrypoint.d" / "07-audit-log-rotate.sh").read_text(encoding="utf-8")
    assert "/usr/local/bin/audit-log-rotate.sh &" in launcher  # tâche de fond : ne bloque pas nginx


def _rotate(tmp_path, max_bytes: str) -> subprocess.CompletedProcess:
    sh = shutil.which("sh")
    if sh is None:
        pytest.skip("sh absent")
    env = {"PATH": "/usr/bin:/bin", "MODSEC_AUDIT_LOG": str(tmp_path / "audit.json"),
           "WAF_AUDIT_MAX_BYTES": max_bytes}
    return subprocess.run([sh, str(WAF / "audit-log-rotate.sh"), "--once"], env=env,
                          capture_output=True, text=True, timeout=30)


def test_audit_log_rotation_keeps_one_generation_and_truncates_in_place(tmp_path):
    log = tmp_path / "audit.json"
    _rotate(tmp_path, "100")  # fichier absent : rien à faire, pas d'erreur
    assert not log.exists()
    log.write_text('{"transaction": 1}\n' * 3, encoding="utf-8")  # 57 octets <= 100 : intact
    assert _rotate(tmp_path, "100").returncode == 0 and log.stat().st_size == 57
    inode = log.stat().st_ino
    log.write_text('{"transaction": 2}\n' * 10, encoding="utf-8")  # 190 octets > 100
    r = _rotate(tmp_path, "100")
    assert r.returncode == 0 and "tronqué" in r.stdout
    assert log.stat().st_size == 0 and log.stat().st_ino == inode  # même fichier (descripteur de ModSec)
    assert (tmp_path / "audit.json.1").read_text(encoding="utf-8").count("transaction") == 10
    assert not (tmp_path / "audit.json.1.tmp").exists()
    log.write_text("x" * 500, encoding="utf-8")
    assert _rotate(tmp_path, "0").returncode == 0 and log.stat().st_size == 500  # 0 = pas de borne


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
    # Routes PUBLIQUES (serveur 8443) ; le listener hôte 9443 du back-office (loopback) n'est pas concerné.
    for route in ("/api/v1/accounts", "/api/v1/transactions", "/api/v1/login", "/api/v1/register", "= /api/v1/auth/step-up"):
        line = next(ln for ln in PUBLIC_SERVER.splitlines() if f"location {route}" in ln)
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
        assert "proxy_connect_timeout 2s;" in line, "réplique morte abandonnée avant le timeout client"


def test_real_ip_trust_is_generated_empty_by_default_and_applied_before_blocking():
    # include realip AVANT le geo de blocage : en mode IP réelle, le blocage vise le vrai client.
    conf = _directives(NGINX)
    assert conf.index("include /etc/nginx/conf/realip.conf;") < conf.index("geo $blocked_source")
    script = (WAF / "docker-entrypoint.d" / "06-trust-forwarded.sh").read_text(encoding="utf-8")
    assert "WAF_TRUST_FORWARDED_FROM" in script and "real_ip_header X-Forwarded-For;" in script
    assert "grep -Eq '^[0-9A-Fa-f:.]+(/[0-9]{1,3})?$'" in script  # IP/CIDR littérale : aucune injection
    assert "06-trust-forwarded.sh /docker-entrypoint.d/06-trust-forwarded.sh" in DOCKERFILE


def test_metrics_is_never_reachable_through_the_waf():
    # `location /` transmet tout au front, qui sert un /metrics interne (sonde Prometheus) : refus explicite.
    assert "location = /metrics { return 404; }" in _directives(NGINX)

def test_plain_http_only_redirects_to_https_and_hsts_is_sent():
    conf = _directives(NGINX)
    plain = re.search(r"server \{\s*listen 8080;(.*?)\n    \}", conf, re.S)
    assert plain, "serveur HTTP clair dédié"
    body = plain.group(1)
    assert "return 301 https://$host$request_uri;" in body and "proxy_pass" not in body
    assert re.search(r"location = /healthz", body), "sonde de vie conservée sur :8080"
    tls = conf[conf.index("listen 8443 ssl;"):]
    assert "listen 8080;" not in tls, "l'API n'est jamais servie en clair"
    assert 'add_header Strict-Transport-Security "max-age=31536000" always;' in conf


def test_modsecurity_audit_log_never_contains_request_bodies():
    import yaml

    env = yaml.safe_load(COMPOSE)["services"]["waf"]["environment"]
    parts = env["MODSEC_AUDIT_LOG_PARTS"]
    assert not set(parts) & set("CIJ"), "pas de corps de requête (mots de passe)"
    assert {"A", "B", "H", "Z"} <= set(parts), "ce que lit waf-exporter (uri, règles)"
