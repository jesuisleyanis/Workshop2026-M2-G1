"""Tests de la source de vérité des features et de l'heuristique de routage."""

import math

import pytest

from resilience_common import IncidentType
from ml.shared.features import (
    FEATURE_NAMES,
    N_FEATURES,
    SIGNAL_Z_MIN,
    classify_incident,
    top_features,
    vector_from_dict,
    vector_to_dict,
    zscores,
)

# Contrat docs/contracts.md §2 — ordre figé.
CONTRACT_ORDER = [
    "req_per_s", "p95_latency_ms", "ratio_4xx", "ratio_5xx",
    "auth_failed_per_s", "waf_blocked_per_s",
    "cpu_pct_max", "mem_pct_max", "db_errors_per_s",
]


def test_order_and_length_match_contract():
    assert list(FEATURE_NAMES) == CONTRACT_ORDER
    assert N_FEATURES == 9
    assert len(set(FEATURE_NAMES)) == N_FEATURES


def test_vector_roundtrip_preserves_order():
    d = {n: float(i) for i, n in enumerate(FEATURE_NAMES)}
    vec = vector_from_dict(d)
    assert vec == [float(i) for i in range(N_FEATURES)]
    assert vector_to_dict(vec) == d


def test_vector_validation():
    with pytest.raises(ValueError):
        vector_to_dict([0.0] * (N_FEATURES - 1))
    with pytest.raises(ValueError):
        vector_to_dict([math.nan] + [0.0] * (N_FEATURES - 1))
    with pytest.raises(KeyError):
        vector_from_dict({"req_per_s": 1.0})


def _z(**overrides: float) -> dict[str, float]:
    z = {n: 0.0 for n in FEATURE_NAMES}
    z.update(overrides)
    return z


@pytest.mark.parametrize(
    "z, expected",
    [
        (_z(req_per_s=9.2, ratio_5xx=7.1, p95_latency_ms=6.0), IncidentType.SERVICE_FLOOD),
        (_z(p95_latency_ms=8.0, ratio_5xx=6.0), IncidentType.SERVICE_FLOOD),
        (_z(auth_failed_per_s=30.0, ratio_4xx=10.0), IncidentType.AUTH_ABUSE),
        (_z(waf_blocked_per_s=25.0, ratio_4xx=8.0), IncidentType.WEB_ATTACK),
        (_z(db_errors_per_s=40.0, ratio_5xx=20.0, p95_latency_ms=9.0), IncidentType.DATA_CORRUPTION),
        (_z(), IncidentType.UNKNOWN),
        (_z(cpu_pct_max=5.0), IncidentType.UNKNOWN),  # anomalie sans signature claire
        (_z(auth_failed_per_s=SIGNAL_Z_MIN - 0.1), IncidentType.UNKNOWN),
    ],
)
def test_classify_each_dominant_signal(z, expected):
    assert classify_incident(z) is expected


def test_dominant_signal_wins_when_several_present():
    # Flood massif avec un peu d'échecs d'auth : le flood domine.
    assert classify_incident(_z(req_per_s=20, auth_failed_per_s=4)) is IncidentType.SERVICE_FLOOD
    # Corruption DB : les 5xx/latence (symptômes) ne doivent PAS faire classer en flood.
    assert (
        classify_incident(_z(db_errors_per_s=15, ratio_5xx=12, p95_latency_ms=10))
        is IncidentType.DATA_CORRUPTION
    )


def test_negative_deviations_are_not_attack_signals():
    assert classify_incident(_z(req_per_s=-9.0, auth_failed_per_s=-5.0)) is IncidentType.UNKNOWN


def test_zscores_use_std_floor():
    means = {n: 0.0 for n in FEATURE_NAMES}
    stds = {n: 0.0 for n in FEATURE_NAMES}  # baseline dégénérée
    vec = [0.0] * N_FEATURES
    vec[FEATURE_NAMES.index("db_errors_per_s")] = 1.0
    z = zscores(vec, means, stds)
    assert math.isfinite(z["db_errors_per_s"])
    assert z["db_errors_per_s"] == pytest.approx(1.0 / 0.05)


def test_top_features_sorted_by_abs_z_and_never_empty():
    vec = [1.0] * N_FEATURES
    z = _z(req_per_s=9.2, ratio_5xx=7.1, auth_failed_per_s=3.0, cpu_pct_max=2.5)
    top = top_features(vec, z, k=3)
    assert [t["name"] for t in top] == ["req_per_s", "ratio_5xx", "auth_failed_per_s"]
    # aucune feature au-dessus du seuil -> on garde quand même la plus déviante
    assert len(top_features(vec, _z(cpu_pct_max=0.5))) == 1
