"""Tests du waf-exporter : parsing des blocages ModSecurity -> événement normalisé, métrique exposée,
suivi du journal d'audit (ticket #12)."""

import json
import sys
import threading
from pathlib import Path

import pytest
from prometheus_client import CollectorRegistry, generate_latest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from waf_exporter import (  # noqa: E402
    METRIC,
    WafBlockEvent,
    WafExporter,
    follow,
    iter_block_events,
    iter_json_objects,
    parse_modsec_line,
)


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


# --------------------------------------------------------------------------- parseur
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


def test_json_objects_can_be_concatenated_or_split_across_chunks():
    # ModSecurity Serial/JSON : pas de garantie d'un objet par ligne ; lecture par morceaux.
    a, b = _modsec_block(rule="1"), _modsec_block(rule="2")
    glued = a + b  # sans retour à la ligne
    chunks = [glued[:25], glued[25:60], glued[60:] + "\n" + _modsec_block(rule="3")[:10], _modsec_block(rule="3")[10:]]
    assert [e.rule for e in iter_block_events(chunks)] == ["1", "2", "3"]
    assert list(iter_json_objects(["pas du json {", " encore du bruit"])) == []


# --------------------------------------------------------------------------- métrique exposée
@pytest.fixture
def exporter():
    return WafExporter(registry=CollectorRegistry())


def test_counter_is_incremented_per_rule_and_exposed_in_prometheus_format(exporter):
    n = exporter.feed([_modsec_block(rule="942100"), _modsec_block(rule="942100"), _modsec_block(rule="930110"),
                       _modsec_block(code=200)])
    assert n == 3
    text = generate_latest(exporter.registry).decode()
    assert f'{METRIC}{{rule="942100"}} 2.0' in text
    assert f'{METRIC}{{rule="930110"}} 1.0' in text
    assert "# TYPE resilience_waf_blocked_total counter" in text


def test_observe_emits_contract_log(exporter, capsys):
    exporter.log.handlers.clear()
    import logging

    from resilience_common.logging import JsonFormatter
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(JsonFormatter("waf"))
    exporter.log.addHandler(h)
    exporter.feed([_modsec_block(rule="941100", ip="10.0.0.9", uri="/x")])
    line = capsys.readouterr().out.strip().splitlines()[-1]
    payload = json.loads(line)
    assert payload["service"] == "waf" and payload["event"] == "waf_blocked" and payload["level"] == "WARNING"
    assert payload["client_ip"] == "10.0.0.9" and payload["http_path"] == "/x" and payload["http_status"] == 403
    assert "941100" in payload["message"]


# --------------------------------------------------------------------------- suivi du journal
def test_follow_waits_for_file_then_streams_appends_and_handles_truncation(tmp_path):
    audit = tmp_path / "audit.json"
    stop = threading.Event()
    got: list[str] = []

    def consume():
        for chunk in follow(audit, from_start=True, poll_s=0.01, stop=stop):
            got.append(chunk)

    t = threading.Thread(target=consume, daemon=True)
    t.start()
    _wait(lambda: t.is_alive(), 1)  # le fichier n'existe pas encore : l'exporteur attend sans planter
    audit.write_text(_modsec_block(rule="1") + "\n", encoding="utf-8")
    _wait(lambda: "".join(got).count("ruleId") == 1)
    with audit.open("a", encoding="utf-8") as fh:
        fh.write(_modsec_block(rule="2") + "\n")
    _wait(lambda: "".join(got).count("ruleId") == 2)
    audit.write_text(_modsec_block(rule="3") + "\n", encoding="utf-8")  # troncature (rotation)
    _wait(lambda: "".join(got).count("ruleId") == 3)
    stop.set()
    t.join(1)
    assert [e.rule for e in iter_block_events(got)] == ["1", "2", "3"]


def test_follow_starts_at_end_by_default_so_restarts_do_not_recount(tmp_path):
    audit = tmp_path / "audit.json"
    audit.write_text(_modsec_block(rule="old") + "\n", encoding="utf-8")
    stop = threading.Event()
    got: list[str] = []
    t = threading.Thread(target=lambda: got.extend(follow(audit, poll_s=0.01, stop=stop)), daemon=True)
    t.start()
    _wait(lambda: t.is_alive(), 0.05)
    with audit.open("a", encoding="utf-8") as fh:
        fh.write(_modsec_block(rule="new") + "\n")
    _wait(lambda: "new" in "".join(got))
    stop.set()
    t.join(1)
    assert [e.rule for e in iter_block_events(got)] == ["new"]


def _wait(cond, timeout: float = 2.0) -> None:
    import time
    deadline = time.time() + timeout
    while time.time() < deadline:
        if cond():
            return
        time.sleep(0.01)
    assert cond(), "condition non atteinte"
