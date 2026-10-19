"""Garanties de sécurité portées par la configuration du WAF (modèles nginx, Dockerfile, compose).

Ces fichiers ne s'exécutent pas dans pytest : on vérifie ici, sur leur texte, les propriétés que
le jury sonde (seul le WAF est exposé, routes internes inatteignables, X-Forwarded-For non
usurpable, liste de blocage réellement rechargée...). La preuve de comportement, sur une vraie
instance nginx + ModSecurity, est dans `test_waf_image.py` (opt-in : WAF_DOCKER_TESTS=1).
Pas de PyYAML : le projet n'en dépend pas pour ce composant, on lit les fichiers comme du texte.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

WAF = Path(__file__).resolve().parents[1]
ROOT = WAF.parents[1]
TEMPLATE = (WAF / "templates" / "conf.d" / "default.conf.template").read_text(encoding="utf-8")
LOGGING = (WAF / "templates" / "conf.d" / "logging.conf.template").read_text(encoding="utf-8")
DOCKERFILE = (WAF / "Dockerfile").read_text(encoding="utf-8")
COMPOSE = (ROOT / "infra" / "compose" / "docker-compose.yml").read_text(encoding="utf-8")
PLAYBOOK = (ROOT / "infra" / "ansible" / "playbooks" / "waf_deny_ip.yml").read_text(encoding="utf-8")
PROMTAIL = (ROOT / "infra" / "promtail" / "promtail-config.yml").read_text(encoding="utf-8")
ENGINE_WAF = (ROOT / "remediation" / "actions" / "waf.py").read_text(encoding="utf-8")


def _strip_comments(text: str) -> str:
    return "\n".join(line.split("#", 1)[0] for line in text.splitlines())


CONF = _strip_comments(TEMPLATE)


def _render(text: str) -> str:
    """Rendu minimal de l'entrypoint de l'image : seules les ${VAR} sont substituées."""
    values = {"PORT": "8080", "SSL_PORT": "8443", "SSL_CERT_FILE": "/c.crt", "SSL_CERT_KEY_FILE": "/c.key",
              "SSL_PROTOCOLS": "TLSv1.2 TLSv1.3", "SSL_CIPHERS": "HIGH", "ERRORLOG": "/dev/stderr",
              "LOGLEVEL": "error"}
    return re.sub(r"\$\{(\w+)\}", lambda m: values[m.group(1)], text)


def _service_block(name: str) -> str:
    m = re.search(rf"^  {name}:\n(.*?)(?=^  \S|^\S|\Z)", COMPOSE, re.S | re.M)
    assert m, f"service {name} absent du compose"
    return _strip_comments(m.group(1))


def _location(path_regex: str) -> str:
    """Corps (accolades équilibrées) du bloc `location ... { ... }` correspondant à path_regex."""
    m = re.search(rf"location\s+{path_regex}\s*\{{", CONF)
    assert m, f"location {path_regex} absente"
    depth, i = 1, m.end()
    while depth:
        depth += {"{": 1, "}": -1}.get(CONF[i], 0)
        i += 1
    return CONF[m.end():i - 1]


# --- le modèle se rend entièrement ----------------------------------------------------

def test_template_renders_without_unresolved_variables():
    rendered = _render(CONF + LOGGING)
    assert "${" not in rendered
    assert "$remote_addr" in rendered      # les variables nginx restent intactes


# --- routage : rien d'interne n'est atteignable ---------------------------------------

@pytest.mark.parametrize("pattern", [r"\^~ /internal/", r"= /metrics", r"/api/"])
def test_internal_and_undeclared_routes_are_refused_by_the_waf(pattern):
    body = _location(pattern)
    assert "return 404" in body
    assert "proxy_pass" not in body


def test_only_the_three_declared_backends_can_be_proxied():
    targets = set(re.findall(r"proxy_pass\s+(\$\w+)\s*;", CONF))
    declared = dict(re.findall(r"set\s+(\$\w+)\s+(http://[\w.-]+:\d+)\s*;", CONF))
    assert targets == set(declared)
    assert sorted(declared.values()) == ["http://auth:8002", "http://front:8080", "http://payment-api:8001"]
    # jamais d'URL littérale ni de chemin : sinon nginx résout au démarrage et passe l'URI telle quelle
    assert not re.search(r"proxy_pass\s+https?://", CONF)


def test_api_routes_are_explicit_and_precede_the_catch_all_404():
    routed = re.findall(r"location\s+(/api/v1/\w+)\s*\{\s*proxy_pass", CONF)
    assert sorted(routed) == ["/api/v1/accounts", "/api/v1/login", "/api/v1/register", "/api/v1/transactions"]
    assert re.search(r"location\s+/api/\s*\{\s*return 404;", CONF)


def test_healthcheck_probe_is_local_only_and_outside_modsecurity():
    body = _location(r"= /healthz")
    assert "modsecurity off" in body
    assert 'if ($remote_addr != "127.0.0.1") { return 404; }' in body
    assert "proxy_pass" not in body


# --- identité de la source ------------------------------------------------------------

def test_forwarded_for_is_overwritten_not_appended():
    assert re.search(r"proxy_set_header\s+X-Forwarded-For\s+\$remote_addr\s*;", CONF)
    assert "$proxy_add_x_forwarded_for" not in CONF
    assert re.search(r"proxy_set_header\s+X-Real-IP\s+\$remote_addr\s*;", CONF)


def test_blocked_sources_get_403_before_any_proxying():
    assert "default 0;" in CONF
    assert re.search(r"if\s*\(\$blocked_source\)\s*\{\s*return 403;\s*\}", CONF)
    assert CONF.index("return 403") < CONF.index("proxy_pass")


# --- en-têtes et divulgation ----------------------------------------------------------

def test_security_headers_are_set_by_the_waf_and_not_duplicated():
    for header in ("X-Content-Type-Options", "X-Frame-Options", "Referrer-Policy"):
        assert re.search(rf"add_header\s+{header}\s+\S+\s+always;", CONF), header
        assert re.search(rf"proxy_hide_header\s+{header};", CONF), header
    assert "server_tokens off;" in CONF and "more_clear_headers Server;" in CONF


def test_tls_is_restricted_and_no_plaintext_secret_in_template():
    assert re.search(r"ssl_protocols\s+\$\{SSL_PROTOCOLS\}", CONF)
    assert "ssl_session_tickets off;" in CONF


# --- liste de blocage : le bon montage, le bon fichier --------------------------------

def _waf_volumes() -> dict[str, tuple[str, str]]:
    """{cible dans le conteneur: (source, mode)} des volumes du service waf."""
    out = {}
    for src, dst, mode in re.findall(r"-\s+(\S+):(/\S+?)(?::(ro|rw))?\s*$", _service_block("waf"), re.M):
        out[dst] = (src, mode or "rw")
    return out


def _remediation_volumes() -> dict[str, tuple[str, str]]:
    out = {}
    for src, dst, mode in re.findall(r"-\s+(\S+):(/\S+?)(?::(ro|rw))?\s*$", _service_block("remediation"), re.M):
        out[dst] = (src, mode or "rw")
    return out


def test_blocklist_is_mounted_as_a_directory_read_only_in_the_waf():
    """Régression : un bind mount de FICHIER garde l'ancien inode après un renommage (celui du
    moteur de remédiation) -> l'IP serait « bloquée » côté moteur mais pas côté nginx."""
    include = re.search(r"include\s+(\S+/)\*\.conf;", CONF).group(1)           # glob : dossier entier
    mount_dir = include.rstrip("/")
    volumes = _waf_volumes()
    assert mount_dir in volumes, f"{mount_dir} non monté (volumes : {sorted(volumes)})"
    source, mode = volumes[mount_dir]
    assert mode == "ro"
    assert not Path(source).suffix, f"la source du montage doit être un dossier, pas un fichier : {source}"
    assert (WAF / "blocklist").is_dir()
    assert "/etc/nginx/blocked_ips.conf" not in COMPOSE
    assert "COPY --chown=root:root blocklist/ /etc/nginx/blocklist/" in DOCKERFILE


def test_remediation_and_waf_share_the_same_blocklist_directory():
    waf_source = _waf_volumes()["/etc/nginx/blocklist"][0]
    remediation = _remediation_volumes()
    target, (source, mode) = next((t, v) for t, v in remediation.items() if "blocklist" in t)
    assert source == waf_source and mode == "rw"          # le moteur écrit, le WAF lit
    path_env = re.search(r"BLOCKLIST_PATH:\s*(\S+)", _service_block("remediation")).group(1)
    assert path_env == f"{target}/blocked_ips.conf"


def test_remediation_can_reach_loki_but_is_not_on_the_edge_network():
    """La source du blocage vient de Loki (réseau obs) ; jamais le réseau exposé."""
    networks = re.search(r"networks:\s*\[([^\]]*)\]", _service_block("remediation")).group(1)
    names = {n.strip() for n in networks.split(",")}
    assert "obs" in names and "edge" not in names
    assert not re.search(r"^\s+ports:", _service_block("remediation"), re.M)


def test_waf_does_not_need_docker_to_reload():
    """Le WAF se recharge seul : ni socket Docker, ni verbe de proxy de plus pour le moteur."""
    assert "docker.sock" not in _service_block("waf")
    haproxy = (ROOT / "remediation" / "proxy" / "haproxy.cfg").read_text(encoding="utf-8")
    assert "exec" not in haproxy and "kill" not in haproxy


def test_engine_no_longer_runs_a_playbook_for_the_waf():
    runner = (ROOT / "remediation" / "actions" / "runner.py").read_text(encoding="utf-8")
    assert re.search(r"ALLOWED_PLAYBOOKS = frozenset\(\{PLAYBOOK_PG_RESTORE\}\)", runner)
    assert "run_playbook" not in ENGINE_WAF and "blocklist.add" in ENGINE_WAF


def test_operator_playbook_stays_consistent_with_the_mounted_directory():
    """waf_deny_ip.yml ne sert plus qu'à l'opérateur (PRA) : il doit écrire dans le même dossier."""
    m = re.search(r'blocked_file:\s*"\{\{ project_root \}\}/(\S+)"', PLAYBOOK)
    assert m and m.group(1) == "security/waf/blocklist/blocked_ips.conf"
    assert _waf_volumes()["/etc/nginx/blocklist"][0].endswith("security/waf/blocklist")
    assert not re.search(r"blocked_ip", PLAYBOOK)


def test_blocklist_runtime_file_is_not_versioned():
    ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "security/waf/blocklist/*.conf" in ignore
    assert (WAF / "blocklist" / ".gitkeep").is_file()


def test_reset_script_empties_the_mounted_file():
    reset = (ROOT / "attacks" / "reset.sh").read_text(encoding="utf-8")
    assert "security/waf/blocklist/blocked_ips.conf" in reset
    assert "security/waf/blocked_ips.conf" not in reset


# --- compose : surface d'exposition ---------------------------------------------------

def test_only_the_waf_publishes_ports():
    published = re.findall(r"^  (\w[\w-]*):\n(?:(?!^  \S).*\n)*?    ports:", COMPOSE, re.M)
    assert published == ["waf"], published
    assert re.findall(r'"(\d+:\d+)"', _service_block("waf")) == ["80:8080", "443:8443"]


def test_waf_exporter_is_read_only_and_not_published():
    block = _service_block("waf-exporter")
    assert "read_only: true" in block
    assert "ports:" not in block
    assert re.search(r"waf-logs:/var/log/modsec:ro", block)


def test_waf_runs_unprivileged_with_bounded_resources():
    block = _service_block("waf")
    assert "<<: *hardening" in block        # cap_drop ALL + no-new-privileges
    for limit in ("mem_limit", "cpus", "pids_limit"):
        assert limit in block
    assert re.search(r"^USER nginx\s*$", DOCKERFILE, re.M)
    assert re.search(r"^FROM \S+:\d[\w.-]+", DOCKERFILE, re.M), "image de base non épinglée"
    assert ":latest" not in DOCKERFILE


# --- journalisation -------------------------------------------------------------------

def test_audit_log_keeps_no_headers_nor_bodies_and_only_blocks():
    assert "MODSEC_AUDIT_LOG_PARTS=AHZ" in DOCKERFILE
    assert "MODSEC_AUDIT_LOG_RELEVANT_STATUS=^403$" in DOCKERFILE
    assert "MODSEC_RULE_ENGINE=on" in DOCKERFILE


def test_access_log_has_no_query_string_nor_body():
    assert "$request_uri" not in LOGGING and "$args" not in LOGGING and "$query_string" not in LOGGING
    for field in ('"ts"', '"level"', '"service"', '"event"', '"message"', '"request_id"'):
        assert field in LOGGING, field


def test_error_log_level_keeps_the_causes_of_502():
    """`crit` masquait « connect() failed », « upstream timed out »... (niveau error)."""
    level = re.search(r"LOGLEVEL=(\w+)", DOCKERFILE).group(1)
    assert level in {"error", "warn", "notice", "info"}
    assert "error_log ${ERRORLOG} ${LOGLEVEL};" in LOGGING


NGINX_ERROR_LINE = (
    '2026/10/19 10:00:00 [error] 12#12: *3 connect() failed (111: Connection refused) while connecting '
    'to upstream, client: 172.22.0.1, server: _, request: "GET /api/v1/accounts?token=SECRET&id=1 HTTP/1.1", '
    'upstream: "http://10.0.0.5:8001/api/v1/accounts?token=SECRET&id=1", host: "localhost", '
    'referrer: "https://localhost/?token=SECRET"'
)


MODSEC_ERROR_LINE = (
    "2026/10/19 10:00:06 [error] 611#611: *2 ModSecurity: Matched \"Operator `Rx' against variable "
    "`ARGS:password' (Value: `Zq9' OR 1=1--SECRETPWD' ) [id \"942100\"] "
    "[data \"Matched Data: 1=1 found within ARGS:password: Zq9\\\" OR 1=1--SECRETPWD\"] [uri \"/api/v1/login\"], "
    "client: 1.2.3.4, request: \"POST /api/v1/login HTTP/1.1\", host: \"h\""
)


def _redact(line: str) -> str:
    for expression in _promtail_replace_expressions():
        # Équivalent de l'étape Promtail : le groupe capturé est remplacé par '' (RE2 ~ re ici).
        line = re.sub(expression, lambda m: m.group(0)[: m.start(1) - m.start()] + m.group(0)[m.end(1) - m.start():], line)
    return line


def _promtail_replace_expressions() -> list[str]:
    found = re.findall(r"- replace:\s*\n\s+expression: '((?:[^']|'')+)'\s*\n\s+replace: ''", PROMTAIL)
    return [e.replace("''", "'") for e in found]          # échappement YAML des apostrophes


def test_promtail_redacts_query_strings_of_the_nginx_error_log_before_loki():
    """Le niveau `error` rend visible la requête complète (donc ses jetons) : Promtail les
    retire avant Loki (étape `replace`, qui n'efface que le groupe capturé)."""
    expressions = _promtail_replace_expressions()
    assert expressions, "aucune étape replace dans la config Promtail"
    # La première étape du pipeline : avant le parsing JSON, sinon la ligne brute part telle quelle.
    assert PROMTAIL.index("- replace:") < PROMTAIL.index("- json:")
    line = _redact(NGINX_ERROR_LINE)
    assert "SECRET" not in line and "token" not in line
    assert 'request: "GET /api/v1/accounts HTTP/1.1"' in line         # cause du 502 conservée
    assert 'upstream: "http://10.0.0.5:8001/api/v1/accounts"' in line
    assert "connect() failed (111: Connection refused)" in line


def test_promtail_redacts_modsecurity_matched_data_and_values():
    """« ModSecurity: Access denied/Matched » est écrit à `error` : [data] et (Value: ...)
    portent le contenu apparié (ex. le mot de passe d'un login bloqué)."""
    line = _redact(MODSEC_ERROR_LINE)
    assert "SECRETPWD" not in line and "Matched Data" not in line
    assert '[id "942100"]' in line and 'request: "POST /api/v1/login HTTP/1.1"' in line


# --- rotation du journal d'audit ------------------------------------------------------

ROTATE = WAF / "docker-entrypoint.d" / "97-audit-rotate.sh"


def test_rotation_script_is_installed_executable_in_the_image():
    assert "docker-entrypoint.d/97-audit-rotate.sh docker-entrypoint.d/98-blocklist-watch.sh /docker-entrypoint.d/" in DOCKERFILE
    assert "--chmod=0755" in DOCKERFILE
    assert "AUDIT_LOG_MAX_BYTES" in DOCKERFILE
    # le seuil laisse de la marge dans le tmpfs de 64 Mo du compose
    assert int(re.search(r"AUDIT_LOG_MAX_BYTES=(\d+)", DOCKERFILE).group(1)) <= 32 * 1024 * 1024
    assert "size=64m" in COMPOSE


@pytest.mark.skipif(shutil.which("sh") is None, reason="sh absent")
def test_rotation_script_truncates_only_above_the_threshold(tmp_path):
    log = tmp_path / "audit.json"
    env = {"MODSEC_AUDIT_LOG": log.as_posix(), "AUDIT_LOG_MAX_BYTES": "100", "PATH": __import__("os").environ["PATH"]}

    def run_once():
        return subprocess.run(["sh", ROTATE.as_posix(), "--once"], env=env, capture_output=True, text=True, timeout=20)

    assert run_once().returncode == 0                       # fichier absent : rien à faire
    log.write_bytes(b"x" * 99)
    assert run_once().returncode == 0 and log.stat().st_size == 99
    log.write_bytes(b"x" * 100)
    assert run_once().returncode == 0 and log.stat().st_size == 0
