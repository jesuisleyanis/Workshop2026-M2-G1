"""Contrat statique de la fonction SOC (R12).

Valide, sans Grafana en vie, que les règles d'alerte SOC sont cohérentes avec :
  - les datasources provisionnées (uid référencés existants) ;
  - la table de décision de remédiation (couverture des incident_type) ;
  - la structure d'alerting unifié (requête -> réduction -> seuil).
"""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
SOC = ROOT / "infra" / "grafana" / "provisioning" / "alerting" / "soc-rules.yml"
DATASOURCES = ROOT / "infra" / "grafana" / "provisioning" / "datasources" / "datasources.yml"
DECISION = ROOT / "remediation" / "decision_table.yml"

# incident_type purement interne, sans signal SOC dédié (fallback moteur).
_NO_SOC = {"unknown"}


def _load(path: Path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _rules() -> list[dict]:
    doc = _load(SOC)
    return [r for g in doc["groups"] for r in g["rules"]]


def test_datasource_uids_are_fixed() -> None:
    uids = {ds.get("uid") for ds in _load(DATASOURCES)["datasources"]}
    assert {"prometheus", "loki"} <= uids, "datasources doivent fixer uid prometheus et loki"


def test_rules_reference_existing_datasources() -> None:
    valid = {ds["uid"] for ds in _load(DATASOURCES)["datasources"]} | {"__expr__"}
    for rule in _rules():
        for q in rule["data"]:
            assert q["datasourceUid"] in valid, (
                f"{rule['uid']}: datasourceUid inconnu {q['datasourceUid']!r}"
            )


def test_condition_points_to_existing_refid() -> None:
    for rule in _rules():
        refids = {q["refId"] for q in rule["data"]}
        assert rule["condition"] in refids, f"{rule['uid']}: condition hors des refId"


def test_rules_have_reduce_before_threshold() -> None:
    # Sans réduction (reduce) entre requête et seuil, l'évaluateur échoue.
    for rule in _rules():
        types = {q["model"].get("type") for q in rule["data"] if q["datasourceUid"] == "__expr__"}
        assert "reduce" in types, f"{rule['uid']}: étape reduce manquante"
        assert "threshold" in types, f"{rule['uid']}: étape threshold manquante"


def test_every_remediable_incident_type_has_a_soc_rule() -> None:
    decision = _load(DECISION)
    incident_types = {r["incident_type"] for r in decision["rules"]} - _NO_SOC
    soc_types = {r["labels"]["incident_type"] for r in _rules()}
    missing = incident_types - soc_types
    assert not missing, f"incident_type sans règle SOC : {sorted(missing)}"
