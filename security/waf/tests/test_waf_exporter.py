"""Tests du waf-exporter : parsing des blocages ModSecurity -> événement normalisé."""

import json
import sys
from pathlib import Path

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
