"""Tests du contrat Red Team <-> Blue Team porté par les scénarios."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from validate_scenarios import validate_dir, validate_scenario  # noqa: E402

SCENARIO_DIR = Path(__file__).resolve().parents[1] / "scenarios"


def test_all_shipped_scenarios_are_valid():
    results = validate_dir(SCENARIO_DIR)
    assert results, "aucun scénario trouvé"
    for name, errors in results.items():
        assert errors == [], f"{name}: {errors}"


def test_four_incident_classes_are_covered():
    results = validate_dir(SCENARIO_DIR)
    import yaml

    types = {
        yaml.safe_load((SCENARIO_DIR / name).read_text())["incident_type"]
        for name in results
    }
    assert {"service_flood", "auth_abuse", "web_attack", "data_corruption"} <= types


def test_missing_remediation_is_rejected():
    bad = {
        "name": "x",
        "objectif": "y",
        "cible": {"service": "z"},
        "signal_attendu": {"metrique": "m"},
        "incident_type": "service_flood",
        "remediation_attendue": [],
        "critere_de_reussite": "c",
    }
    errors = validate_scenario(bad)
    assert any("remediation" in e for e in errors)


def test_invalid_incident_type_is_rejected():
    bad = {
        "name": "x",
        "objectif": "y",
        "cible": {"service": "z"},
        "signal_attendu": {"metrique": "m"},
        "incident_type": "nope",
        "remediation_attendue": ["restart_service"],
        "critere_de_reussite": "c",
    }
    errors = validate_scenario(bad)
    assert any("incident_type" in e for e in errors)
