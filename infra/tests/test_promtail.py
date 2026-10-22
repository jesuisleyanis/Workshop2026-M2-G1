"""Contrat Promtail / Loki (vérifiable sans Docker).

- Label `service` d'un flux Loki = nom du service Compose émetteur : l'événement `waf_blocked`
  vient du conteneur `waf-exporter`, toute requête LogQL qui le cherche doit viser ce label
  (sinon `confirm_waf_block` et la source `from_loki` de la remédiation ne trouvent rien).
- La remédiation joint Loki (réseau `obs`) sans jamais être sur `edge`.
- Masquage, avant Loki, de ce que l'error_log du WAF recopie de la requête.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
PROMTAIL = yaml.safe_load((ROOT / "infra" / "promtail" / "promtail-config.yml").read_text(encoding="utf-8"))
COMPOSE = yaml.safe_load((ROOT / "infra" / "compose" / "docker-compose.yml").read_text(encoding="utf-8"))
SCRAPE = PROMTAIL["scrape_configs"][0]
STAGES = SCRAPE["pipeline_stages"]

# Fichiers qui portent une requête LogQL sur `waf_blocked` (code, scénario, PCA).
WAF_BLOCKED_QUERY_FILES = (
    "remediation/actions/waf.py",
    "ml/detector/events.py",
    "attacks/scenarios/web_attack.yml",
    "docs/pca-pra.md",
)


# --------------------------------------------------------------------------- label `service`
def test_service_label_is_the_compose_service_name() -> None:
    relabel = {r["target_label"]: r["source_labels"] for r in SCRAPE["relabel_configs"]}
    assert relabel["service"] == ["__meta_docker_container_label_com_docker_compose_service"]
    # Le champ JSON `service` est extrait mais jamais promu en label (il écraserait celui du Compose).
    promoted = [s["labels"] for s in STAGES if "labels" in s]
    assert all("service" not in labels for labels in promoted)


def test_waf_blocked_queries_target_the_emitting_compose_service() -> None:
    assert "waf-exporter" in COMPOSE["services"]
    for rel in WAF_BLOCKED_QUERY_FILES:
        text = (ROOT / rel).read_text(encoding="utf-8").replace('\\"', '"')
        # Sélecteur par label `event` (indexé) ou filtre de ligne : le label `service` doit être waf-exporter.
        selectors = re.findall(r'\{service="([^"]+)"(?:, event="waf_blocked"\}|\} \|= "waf_blocked")', text)
        assert selectors, f"{rel} : aucune requête waf_blocked trouvée"
        assert set(selectors) == {"waf-exporter"}, f"{rel} : {selectors} (le WAF n'émet pas waf_blocked)"


def test_remediation_reaches_loki_on_obs_but_never_sits_on_edge() -> None:
    svc = COMPOSE["services"]
    assert "obs" in svc["remediation"]["networks"] and "edge" not in svc["remediation"]["networks"]
    assert "ports" not in svc["remediation"]
    assert svc["loki"]["networks"] == ["obs"] and "ports" not in svc["loki"]
    assert COMPOSE["networks"]["obs"].get("internal") is True


# --------------------------------------------------------------------------- masquage
NGINX_ERROR_LINE = (
    '2026/10/19 10:00:00 [error] 12#12: *3 connect() failed (111: Connection refused) while connecting '
    'to upstream, client: 172.22.0.1, server: _, request: "GET /api/v1/accounts?token=SECRET&id=1 HTTP/1.1", '
    'upstream: "http://10.0.0.5:8001/api/v1/accounts?token=SECRET&id=1", host: "localhost", '
    'referrer: "https://localhost/?token=SECRET"'
)
MODSEC_ERROR_LINE = (
    "2026/10/19 10:00:06 [error] 611#611: *2 ModSecurity: Access denied with code 403 (phase 2). "
    "Matched \"Operator `Rx' against variable `ARGS:password' (Value: `Zq9' OR 1=1--SECRETPWD' ) "
    "[id \"942100\"] [data \"Matched Data: 1=1 found within ARGS:password: Zq9\\\" OR 1=1--SECRETPWD\"] "
    "[uri \"/api/v1/auth/login\"], client: 1.2.3.4, request: \"POST /api/v1/auth/login HTTP/1.1\", host: \"h\""
)
CONTRACT_LINE = ('{"ts":"2026-10-19T10:00:00Z","level":"WARNING","service":"waf","event":"waf_blocked",'
                 '"client_ip":"203.0.113.7","http_path":"/api/v1/x","http_status":403,"request_id":"r1"}')


def _replace_expressions() -> list[str]:
    exprs = [s["replace"] for s in STAGES if "replace" in s]
    assert all(e.get("replace", "") == "" for e in exprs), "masquage = groupe capturé remplacé par ''"
    return [e["expression"] for e in exprs]


def _redact(line: str) -> str:
    """Équivalent de l'étape Promtail `replace` : seul le groupe capturé est effacé (RE2 ~ re ici)."""
    for expression in _replace_expressions():
        line = re.sub(expression,
                      lambda m: m.group(0)[: m.start(1) - m.start()] + m.group(0)[m.end(1) - m.start():], line)
    return line


def test_redaction_runs_before_json_parsing() -> None:
    kinds = [next(iter(s)) for s in STAGES]
    assert "replace" in kinds and kinds.index("replace") < kinds.index("json")


def test_nginx_error_log_query_strings_are_redacted() -> None:
    line = _redact(NGINX_ERROR_LINE)
    assert "SECRET" not in line and "token" not in line
    assert 'request: "GET /api/v1/accounts HTTP/1.1"' in line          # cause d'un 502 conservée
    assert 'upstream: "http://10.0.0.5:8001/api/v1/accounts"' in line
    assert "connect() failed (111: Connection refused)" in line


def test_modsecurity_matched_data_and_values_are_redacted() -> None:
    line = _redact(MODSEC_ERROR_LINE)
    assert "SECRETPWD" not in line
    assert '[id "942100"]' in line and '[uri "/api/v1/auth/login"]' in line  # tri SOC toujours possible
    assert '[data ""]' in line and "(Value: `' )" in line


def test_contract_json_lines_are_left_untouched() -> None:
    assert _redact(CONTRACT_LINE) == CONTRACT_LINE
