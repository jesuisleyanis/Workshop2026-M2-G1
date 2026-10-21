"""Contrat de la chaîne de détection rapide (< 5 s, docs/plan-amelioration-detection.md).

Verrouille les réglages dont dépend la latence ET la validité du modèle : les fenêtres que le
collector mesure doivent être celles sur lesquelles le modèle a été capturé et calibré.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = yaml.safe_load((ROOT / "infra/compose/docker-compose.yml").read_text(encoding="utf-8"))["services"]
PROM = yaml.safe_load((ROOT / "infra/prometheus/prometheus.yml").read_text(encoding="utf-8"))
#: Jobs dont les métriques alimentent les features les plus précoces (débit, erreurs, auth, WAF).
FAST_JOBS = {"payment-api", "auth", "waf-exporter"}


def _seconds(value: str) -> float:
    m = re.fullmatch(r"(\d+(?:\.\d+)?)(ms|s|m)", str(value))
    assert m, f"durée illisible : {value!r}"
    return float(m.group(1)) * {"ms": 0.001, "s": 1, "m": 60}[m.group(2)]


def _job(name: str) -> dict:
    return next(j for j in PROM["scrape_configs"] if j["job_name"] == name)


def test_detection_signals_are_scraped_every_second():
    for name in FAST_JOBS:
        job = _job(name)
        assert _seconds(job["scrape_interval"]) <= 1, f"{name} : scrape > 1 s"
        assert _seconds(job["scrape_timeout"]) < _seconds(job["scrape_interval"])


def test_collector_window_holds_enough_samples_and_collects_every_second():
    env = COMPOSE["collector"]["environment"]
    window = _seconds(env["PROM_RATE_WINDOW"])
    assert float(env["COLLECT_INTERVAL_SECONDS"]) <= 1
    for name in FAST_JOBS:  # rate() fiable : au moins 4 échantillons dans la fenêtre
        assert window >= 4 * _seconds(_job(name)["scrape_interval"])
    assert window <= 10, "fenêtre longue = signal dilué = détection lente"


def test_detector_long_polls_the_collector():
    env = COMPOSE["detector"]["environment"]
    assert float(env["FEATURES_WAIT_SECONDS"]) > 0
    assert float(env["POLL_INTERVAL_SECONDS"]) <= 1


def test_contract_window_matches_the_collector():
    from ml.shared.features import WINDOW_SECONDS

    assert WINDOW_SECONDS == _seconds(COMPOSE["collector"]["environment"]["PROM_RATE_WINDOW"])


def test_detector_and_remediation_can_read_loki():
    # detector : IP source dominante (logs WAF) ; remediation : confirm_waf_block. Loki n'est que sur `obs`.
    assert "obs" in COMPOSE["loki"]["networks"]
    for name in ("detector", "remediation"):
        assert "obs" in COMPOSE[name]["networks"], f"{name} doit joindre Loki (réseau obs)"
