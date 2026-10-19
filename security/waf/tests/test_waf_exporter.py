"""Tests du waf-exporter : parsing des blocages ModSecurity -> événement normalisé."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from waf_exporter import WafBlockEvent, iter_block_events, parse_modsec_line  # noqa: E402


def _modsec_block(rule="942100", ip="192.168.137.50", uri="/api/v1/login", code=403):
    return json.dumps(
        {
            "transaction": {
                "client_ip": ip,
                "request": {"uri": uri},
                "response": {"http_code": code},
                "messages": [{"details": {"ruleId": rule}}],
            }
        }
    )


def test_parse_block_line_extracts_rule_and_ip():
    event = parse_modsec_line(_modsec_block())
    assert isinstance(event, WafBlockEvent)
    assert event.rule == "942100"
    assert event.client_ip == "192.168.137.50"
    assert event.http_status == 403


def test_non_blocked_request_is_ignored():
    # 200 => pas un blocage
    assert parse_modsec_line(_modsec_block(code=200)) is None


def test_invalid_line_is_tolerated():
    assert parse_modsec_line("ceci n'est pas du json") is None
    assert parse_modsec_line("") is None


def test_log_payload_matches_contract():
    event = parse_modsec_line(_modsec_block(rule="930110", uri="/etc/passwd"))
    log = event.to_log()
    # Champs obligatoires du contrat §1
    for field in ("level", "service", "event", "message"):
        assert field in log
    assert log["service"] == "waf"
    assert log["event"] == "waf_blocked"
    assert log["rule"] == "930110"


def test_iter_block_events_filters_stream():
    lines = [
        _modsec_block(rule="942100"),
        "bruit",
        _modsec_block(code=200),  # ignoré
        _modsec_block(rule="930110"),
    ]
    events = list(iter_block_events(lines))
    assert [e.rule for e in events] == ["942100", "930110"]


# --- choix de la règle, contrat de log ------------------------------------------------

def _modsec_multi(rule_ids, code=403, uri="/api/v1/accounts?id=1%27%20OR%201=1"):
    return json.dumps({"transaction": {
        "client_ip": "192.168.137.50", "request": {"uri": uri}, "response": {"http_code": code},
        "messages": [{"details": {"ruleId": r}} for r in rule_ids]}})


def test_detection_rule_preferred_over_protocol_and_evaluation_rules():
    from waf_exporter import pick_rule

    event = parse_modsec_line(_modsec_multi(["920350", "942100", "949110"]))
    assert event.rule == "942100"                                   # SQLi, pas l'hôte numérique
    assert pick_rule([{"details": {"ruleId": "920350"}}, {"details": {"ruleId": "949110"}}]) == "920350"
    assert pick_rule([{"details": {"ruleId": "949110"}}]) == "949110"
    assert pick_rule([{"details": {}}]) == "unknown"


def test_http_path_drops_the_attack_query_string():
    assert parse_modsec_line(_modsec_multi(["942100"])).http_path == "/api/v1/accounts"


def test_log_has_every_mandatory_contract_field():
    log = parse_modsec_line(_modsec_multi(["942100"])).to_log(ts="2026-10-19T10:00:00.000Z")
    for field in ("ts", "level", "service", "event", "message", "request_id"):
        assert field in log
    assert log["ts"] == "2026-10-19T10:00:00.000Z" and log["request_id"] is None


@pytest.mark.parametrize("line", [
    "[]", '"texte"', '{"transaction": {"response": {"http_code": "x"}, "messages": [{}]}}',
    '{"transaction": "pas un objet"}',
    '{"transaction": {"response": "x", "messages": [{}]}}',
    '{"transaction": {"response": {"http_code": 403}, "messages": ["texte"], "request": 3}}',
])
def test_odd_json_is_ignored(line):
    assert parse_modsec_line(line) is None


# --- suivi du journal (tail -F) -------------------------------------------------------

def _script(*steps):
    """`sleep` simulé : chaque appel exécute l'étape suivante ; `stop` quand il n'y en a plus."""
    pending = list(steps)
    state = {"done": False}

    def sleep(_):
        if pending:
            pending.pop(0)()
        else:
            state["done"] = True

    return sleep, (lambda: state["done"])


def test_follow_waits_for_file_then_yields_appended_complete_lines(tmp_path):
    from waf_exporter import follow

    log = tmp_path / "audit.json"

    def create():
        log.write_text("ancienne ligne\n", encoding="utf-8")

    def append_partial():
        with log.open("a", encoding="utf-8") as fh:
            fh.write('{"a": 1}\n{"b"')

    def finish():
        with log.open("a", encoding="utf-8") as fh:
            fh.write(': 2}\n')

    sleep, stop = _script(create, append_partial, finish)
    # from_end=True mais fichier absent au démarrage : le fichier créé ensuite est lu en entier
    lines = list(follow(str(log), from_end=True, poll_s=0, should_stop=stop, sleep=sleep))
    assert lines == ["ancienne ligne", '{"a": 1}', '{"b": 2}']


def test_follow_skips_existing_content_and_survives_truncation(tmp_path):
    from waf_exporter import follow

    log = tmp_path / "audit.json"
    log.write_text("déjà là\n", encoding="utf-8")

    def append():
        with log.open("a", encoding="utf-8") as fh:
            fh.write("nouvelle\n")

    def truncate():
        log.write_text("après rotation\n", encoding="utf-8")

    sleep, stop = _script(append, truncate)
    lines = list(follow(str(log), from_end=True, poll_s=0, should_stop=stop, sleep=sleep))
    assert lines == ["nouvelle", "après rotation"]


def test_run_counts_by_rule_and_logs_json():
    import io

    from prometheus_client import CollectorRegistry
    from waf_exporter import make_counter, run

    registry = CollectorRegistry()
    counter = make_counter(registry)
    out = io.StringIO()
    n = run([_modsec_block(rule="942100"), _modsec_block(code=200), _modsec_multi(["920350", "942100"]),
             _modsec_block(rule="930110")], counter, out)
    assert n == 3
    value = registry.get_sample_value
    assert value("resilience_waf_blocked_total", {"rule": "942100"}) == 2
    assert value("resilience_waf_blocked_total", {"rule": "930110"}) == 1
    logs = [json.loads(line) for line in out.getvalue().splitlines()]
    assert [log["event"] for log in logs] == ["waf_blocked"] * 3
