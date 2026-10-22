"""Contrat statique du dashboard Grafana provisionné (R7 observabilité, démo 5 temps).

Valide, sans Grafana en vie, que le dashboard « RESILIENCE-ALPHA — Supervision SOC » :
  - est bien chargé par un provider pointant dans le volume monté par le compose ;
  - ne référence que les datasources provisionnées et des métriques du contrat (§2) ;
  - affiche le seuil ML réellement calibré (pas une valeur figée divergente) ;
  - a une grille cohérente (ids uniques, pas de chevauchement, un seul axe Y par graphe).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
PROVISIONING = ROOT / "infra" / "grafana" / "provisioning"
PROVIDER = PROVISIONING / "dashboards" / "dashboards.yml"
DASHBOARD = PROVISIONING / "dashboards" / "resilience-overview.json"
DATASOURCES = PROVISIONING / "datasources" / "datasources.yml"
COMPOSE = ROOT / "infra" / "compose" / "docker-compose.yml"
METRICS = ROOT / "libs" / "python" / "resilience_common" / "src" / "resilience_common" / "metrics.py"
CALIBRATION = ROOT / "ml" / "training" / "data" / "calibration.json"

_HISTO_SUFFIX = re.compile(r"_(bucket|count|sum)$")


def _dashboard() -> dict:
    return json.loads(DASHBOARD.read_text(encoding="utf-8"))


def _panels() -> list[dict]:
    return [p for p in _dashboard()["panels"] if p["type"] != "row"]


def _exprs() -> list[str]:
    return [t["expr"] for p in _panels() for t in p.get("targets", []) if "expr" in t]


def test_provider_path_is_inside_compose_mount() -> None:
    providers = yaml.safe_load(PROVIDER.read_text(encoding="utf-8"))["providers"]
    assert providers, "aucun provider de dashboards"
    compose = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
    mounts = compose["services"]["grafana"]["volumes"]
    assert "../grafana/provisioning:/etc/grafana/provisioning:ro" in mounts
    for prov in providers:
        assert prov["type"] == "file"
        assert prov["options"]["path"].startswith("/etc/grafana/provisioning/dashboards")


def test_home_dashboard_is_the_provisioned_file() -> None:
    env = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))["services"]["grafana"]["environment"]
    home = env["GF_DASHBOARDS_DEFAULT_HOME_DASHBOARD_PATH"]
    assert home == f"/etc/grafana/provisioning/dashboards/{DASHBOARD.name}"


def test_dashboard_identity_is_fixed() -> None:
    dash = _dashboard()
    assert dash["uid"] == "resilience-overview", "uid stable : liens et favoris en dépendent"
    assert dash["title"]
    assert dash.get("id") is None, "un id figé casse le provisioning sur une autre instance"


def test_panels_use_provisioned_datasources() -> None:
    uids = {ds["uid"] for ds in yaml.safe_load(DATASOURCES.read_text(encoding="utf-8"))["datasources"]}
    dash = _dashboard()
    sources = [p.get("datasource") for p in _panels()]
    sources += [t.get("datasource") for p in _panels() for t in p.get("targets", [])]
    sources += [a.get("datasource") for a in dash["annotations"]["list"] if not a.get("builtIn")]
    sources += [v.get("datasource") for v in dash["templating"]["list"]]
    for ds in filter(None, sources):
        assert ds["uid"] in uids, f"datasource inconnue {ds!r}"


def test_resilience_metrics_exist_in_contract() -> None:
    declared = set(re.findall(r'"(resilience_\w+)"', METRICS.read_text(encoding="utf-8")))
    used = {_HISTO_SUFFIX.sub("", m) for e in _exprs() for m in re.findall(r"resilience_\w+", e)}
    assert used, "le dashboard doit exploiter les métriques du contrat"
    assert used <= declared, f"métriques hors contrat : {sorted(used - declared)}"


def test_demo_signals_are_all_displayed() -> None:
    # Les 5 temps de la démo : score ML, actions, MTTD/MTTR, transaction de contrôle, signaux SOC.
    joined = "\n".join(_exprs())
    for metric in ("resilience_anomaly_score", "resilience_remediation_actions_total", "resilience_mttd_seconds",
                   "resilience_mttr_seconds", "resilience_transactions_total", "resilience_waf_blocked_total",
                   "resilience_auth_logins_total", "resilience_db_errors_total"):
        assert metric in joined, f"{metric} absent du dashboard"
    assert any(p["type"] == "alertlist" for p in _panels()), "état des règles SOC absent"


def test_anomaly_threshold_matches_calibration() -> None:
    expected = json.loads(CALIBRATION.read_text(encoding="utf-8"))["threshold"]
    score_panels = [p for p in _panels()
                    if any("resilience_anomaly_score" in t.get("expr", "") for t in p.get("targets", []))]
    assert score_panels
    for p in score_panels:
        values = [s["value"] for s in p["fieldConfig"]["defaults"]["thresholds"]["steps"] if s["value"] is not None]
        assert values == [expected], f"{p['title']}: seuil {values} != calibration {expected}"


def test_grid_ids_unique_and_no_overlap() -> None:
    panels = _dashboard()["panels"]
    ids = [p["id"] for p in panels]
    assert len(ids) == len(set(ids)), "ids de panneaux dupliqués"
    cells: dict[tuple[int, int], str] = {}
    for p in panels:
        g = p["gridPos"]
        assert 0 <= g["x"] and g["x"] + g["w"] <= 24, f"{p['title']} déborde de la grille"
        for x in range(g["x"], g["x"] + g["w"]):
            for y in range(g["y"], g["y"] + g["h"]):
                assert (x, y) not in cells, f"{p['title']} chevauche {cells[(x, y)]}"
                cells[(x, y)] = p["title"]


def test_no_dual_axis() -> None:
    for p in _panels():
        for o in p.get("fieldConfig", {}).get("overrides", []):
            for prop in o["properties"]:
                assert not (prop["id"] == "custom.axisPlacement" and prop["value"] == "right"), (
                    f"{p['title']}: double axe Y interdit (deux unités = deux graphes)")
