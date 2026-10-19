"""Table de décision : chargement, sélection par incident_type, invariants de sécurité."""

from __future__ import annotations

import pytest
import yaml
from conftest import TABLE_PATH, make_table
from decision import DecisionTableError, load_decision_table, parse_decision_table
from resilience_common import IncidentType

EXPECTED = {
    IncidentType.SERVICE_FLOOD: ["waf_block_ip", "restart_service"],
    IncidentType.AUTH_ABUSE: ["waf_block_ip", "tighten_rate_limit"],
    IncidentType.WEB_ATTACK: ["confirm_waf_block", "waf_blacklist_ip"],
    IncidentType.DATA_CORRUPTION: ["restore_pg_dump"],
    IncidentType.UNKNOWN: ["dry_run_report"],
}


def test_loads_yaml_with_contract_defaults():
    t = load_decision_table(TABLE_PATH)
    assert t.version == "1.0"
    assert (t.defaults.cooldown_seconds, t.defaults.max_attempts, t.defaults.dry_run) == (60, 3, False)
    assert len(t.rules) == 5


@pytest.mark.parametrize("incident_type,actions", EXPECTED.items(), ids=lambda v: getattr(v, "value", str(v)))
def test_selects_expected_sequence_for_each_of_the_five_types(incident_type, actions):
    rule = load_decision_table(TABLE_PATH).rule_for(incident_type)
    assert [a.type for a in rule.actions] == actions
    assert rule.verify == "verify_tx"
    assert rule.escalation == "notify_operator"


def test_params_come_from_the_file_not_from_code():
    t = load_decision_table(TABLE_PATH)
    flood = t.rule_for(IncidentType.SERVICE_FLOOD)
    assert flood.actions[1].params == {"service": "payment-api"}
    assert t.rule_for(IncidentType.AUTH_ABUSE).actions[1].params == {"service": "auth", "factor": 0.5}


def test_service_flood_is_availability_and_data_corruption_is_restore_never_mixed():
    t = load_decision_table(TABLE_PATH)
    flood = {a.type for a in t.rule_for(IncidentType.SERVICE_FLOOD).actions}
    corruption = {a.type for a in t.rule_for(IncidentType.DATA_CORRUPTION).actions}
    assert "restore_pg_dump" not in flood and {"waf_block_ip", "restart_service"} <= flood
    assert corruption == {"restore_pg_dump"}
    assert not corruption & {"restart_service", "recreate_service", "waf_block_ip"}


def _raw():
    return yaml.safe_load(TABLE_PATH.read_text(encoding="utf-8"))


def _rule(data, t):
    return next(r for r in data["rules"] if r["incident_type"] == t)


def test_refuses_restore_inside_service_flood():
    data = _raw()
    _rule(data, "service_flood")["actions"].append({"type": "restore_pg_dump", "params": {"backup": "latest"}})
    with pytest.raises(DecisionTableError, match="réservé à data_corruption"):
        parse_decision_table(data)


def test_refuses_restart_inside_data_corruption():
    data = _raw()
    _rule(data, "data_corruption")["actions"].insert(0, {"type": "restart_service", "params": {"service": "payment-api"}})
    with pytest.raises(DecisionTableError, match="restart/recreate"):
        parse_decision_table(data)


def test_data_corruption_must_restore():
    data = _raw()
    _rule(data, "data_corruption")["actions"] = [{"type": "dry_run_report", "params": {}}]
    with pytest.raises(DecisionTableError, match="restore_pg_dump"):
        parse_decision_table(data)


def test_unknown_cannot_hold_destructive_actions():
    data = _raw()
    _rule(data, "unknown")["actions"].append({"type": "restart_service", "params": {"service": "auth"}})
    with pytest.raises(DecisionTableError, match="destructive"):
        parse_decision_table(data)


def test_refuses_missing_type_unknown_action_extra_keys_and_bad_params():
    data = _raw()
    data["rules"] = [r for r in data["rules"] if r["incident_type"] != "unknown"]
    with pytest.raises(DecisionTableError, match="sans règle"):
        parse_decision_table(data)

    data = _raw()
    _rule(data, "service_flood")["actions"][0]["type"] = "rm_rf"
    with pytest.raises(DecisionTableError, match="inconnue"):
        parse_decision_table(data)

    data = _raw()
    data["defaults"]["surprise"] = 1  # schéma exact du contrat : pas de clé inventée
    with pytest.raises(DecisionTableError):
        parse_decision_table(data)

    data = _raw()
    _rule(data, "auth_abuse")["actions"][1]["params"]["factor"] = 3
    with pytest.raises(DecisionTableError, match="factor"):
        parse_decision_table(data)


def test_helper_overrides_defaults():
    t = make_table(cooldown=5, max_attempts=2, dry_run=True)
    assert (t.defaults.cooldown_seconds, t.defaults.max_attempts, t.defaults.dry_run) == (5, 2, True)
