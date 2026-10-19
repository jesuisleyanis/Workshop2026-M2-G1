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


# ------------------------------------------------------------------ routage SOC -> remédiation (I6, #13)
PROM_RULES = ROOT / "infra" / "prometheus" / "rules" / "soc.yml"
PROMETHEUS = ROOT / "infra" / "prometheus" / "prometheus.yml"
ALERTMANAGER = ROOT / "infra" / "alertmanager" / "alertmanager.yml"
COMPOSE = ROOT / "infra" / "compose" / "docker-compose.yml"


def _grafana_threshold(rule: dict) -> tuple[str, float]:
    expr = next(q["model"]["expr"] for q in rule["data"] if q["datasourceUid"] == "prometheus")
    thr = next(q["model"] for q in rule["data"] if q["model"].get("type") == "threshold")
    return expr, float(thr["conditions"][0]["evaluator"]["params"][0])


def _prom_rules() -> list[dict]:
    return [r for g in _load(PROM_RULES)["groups"] for r in g["rules"]]


def test_prometheus_rules_mirror_grafana_rules_expression_threshold_and_incident_type() -> None:
    by_type = {r["labels"]["incident_type"]: r for r in _prom_rules()}
    for g in _rules():
        itype = g["labels"]["incident_type"]
        assert itype in by_type, f"règle Prometheus manquante pour {itype}"
        expr, threshold = _grafana_threshold(g)
        p = by_type[itype]
        assert p["expr"].replace(" ", "") == f"{expr}>{threshold:g}".replace(" ", ""), f"{itype}: expression divergente"
        assert p["annotations"]["expr"] == expr, f"{itype}: annotation expr (evidence) divergente"
        assert p["labels"]["severity"] == g["labels"]["severity"]
        assert "service" in p["labels"], f"{itype}: label service attendu par l'adaptateur"
        assert p["for"] == g["for"]


def test_prometheus_feeds_alertmanager_with_soc_rules() -> None:
    cfg = _load(PROMETHEUS)
    assert any(rf.startswith("/etc/prometheus/rules/") for rf in cfg["rule_files"])
    targets = [t for am in cfg["alerting"]["alertmanagers"] for sc in am["static_configs"] for t in sc["targets"]]
    assert targets == ["alertmanager:9093"]
    prom = _load(COMPOSE)["services"]["prometheus"]
    assert any(v.startswith("../prometheus/rules:/etc/prometheus/rules") for v in prom["volumes"])


def test_alertmanager_posts_authenticated_webhook_to_the_adapter_route() -> None:
    cfg = _load(ALERTMANAGER)
    receiver = next(r for r in cfg["receivers"] if r["name"] == cfg["route"]["receiver"])
    wh = receiver["webhook_configs"][0]
    assert wh["url"] == "http://remediation:8005/events/alertmanager"
    assert wh["send_resolved"] is False
    auth = wh["http_config"]["authorization"]
    assert auth["type"] == "Bearer" and auth["credentials_file"] == "/run/secrets/remediation_token"
    assert "credentials:" not in ALERTMANAGER.read_text(encoding="utf-8"), "jamais de token en clair"
    compose = _load(COMPOSE)
    assert compose["secrets"]["remediation_token"] == {"environment": "REMEDIATION_TOKEN"}
    am = compose["services"]["alertmanager"]
    assert am["secrets"] == ["remediation_token"] and "app" in am["networks"] and "ports" not in am
