"""Tests de l'entraînement : le modèle s'entraîne, sérialise, et sépare normal / attaque."""

import hashlib
import json

import joblib
import numpy as np
import pytest

from ml.shared.features import FEATURE_NAMES, N_FEATURES, vector_from_dict
from ml.training.dataset import ATTACK_KINDS, generate_attack, generate_baseline
from ml.training.train import anomaly_scores, main, save, train


@pytest.fixture(scope="module")
def trained():
    # Version allégée pour la vitesse des tests ; mêmes hyperparamètres clés que la prod.
    return train(n_samples=6000, seed=7, version="test", n_estimators=100)


def test_dataset_shape_and_reproducibility():
    a, b = generate_baseline(500, seed=1), generate_baseline(500, seed=1)
    assert a.shape == (500, N_FEATURES)
    assert np.array_equal(a, b)
    assert (a >= 0).all()
    assert (a[:, FEATURE_NAMES.index("ratio_4xx")] <= 1).all()


def test_model_distinguishes_normal_from_attack(trained):
    model, stats = trained
    normal = {
        "req_per_s": 20.0, "p95_latency_ms": 90.0, "ratio_4xx": 0.02, "ratio_5xx": 0.002,
        "auth_failed_per_s": 0.1, "waf_blocked_per_s": 0.1, "cpu_pct_max": 19.0,
        "mem_pct_max": 34.0, "db_errors_per_s": 0.0,
    }
    attack = dict(normal, req_per_s=420.0, p95_latency_ms=3500.0, ratio_5xx=0.34, cpu_pct_max=95.0)
    s_normal, s_attack = anomaly_scores(model, np.array([vector_from_dict(normal), vector_from_dict(attack)]))
    assert s_normal < stats["threshold"] < s_attack
    assert s_attack - s_normal > 0.15


def test_lone_spike_is_a_known_model_blind_spot_covered_by_guardrail(trained):
    """Limite documentée : un pic extrême sur UNE seule feature dilue le score IsolationForest
    (9 features, tirage uniforme). Le garde-fou statistique est là pour ce cas précis."""
    from ml.shared.features import zscores

    model, stats = trained
    vec = dict(stats["mean"], req_per_s=600.0)
    row = np.array([vector_from_dict(vec)])
    assert anomaly_scores(model, row)[0] < stats["threshold"]  # le modèle seul le rate
    z = zscores(row[0], stats["mean"], stats["std"])
    assert max(z.values()) >= stats["guardrail_z"]  # le filet le rattrape


def test_guardrail_is_calibrated_above_every_baseline_z(trained):
    _, stats = trained
    assert stats["guardrail_z"] >= 15.0
    assert stats["guardrail_z"] >= 1.5 * stats["baseline_max_z"] - 0.01
    assert stats["evaluation"]["normal_heldout"]["guardrail_false_positive_rate"] == 0.0


@pytest.mark.parametrize("kind", ATTACK_KINDS)
def test_attack_detection_rate_and_low_false_positives(trained, kind):
    model, stats = trained
    thr = stats["threshold"]
    attack = anomaly_scores(model, generate_attack(kind, 500, seed=3))
    normal = anomaly_scores(model, generate_baseline(2000, seed=99))
    assert (attack >= thr).mean() >= 0.90
    assert (normal >= thr).mean() <= 0.01


def test_baseline_stats_content(trained):
    _, stats = trained
    assert stats["feature_names"] == list(FEATURE_NAMES)
    assert set(stats["mean"]) == set(stats["std"]) == set(FEATURE_NAMES)
    assert 0.5 <= stats["threshold"] < 1.0
    assert set(stats["evaluation"]["attacks"]) == set(ATTACK_KINDS)


def test_save_writes_versioned_artifacts_with_hash(trained, tmp_path):
    model, stats = trained
    stats = dict(stats)
    vdir = save(model, stats, tmp_path)
    assert vdir.name == "vtest"
    for base in (vdir, tmp_path):
        assert (base / "model.joblib").is_file() and (base / "baseline_stats.json").is_file()
    saved = json.loads((tmp_path / "baseline_stats.json").read_text())
    assert saved["model_sha256"] == hashlib.sha256((tmp_path / "model.joblib").read_bytes()).hexdigest()
    payload = joblib.load(tmp_path / "model.joblib")
    assert payload["feature_names"] == list(FEATURE_NAMES) and payload["model_version"] == "test"


def test_cli_is_reproducible(tmp_path):
    args = ["--n-samples", "1500", "--n-estimators", "30", "--seed", "5", "--version", "9.9.9"]
    assert main([*args, "--out", str(tmp_path / "a")]) == 0
    assert main([*args, "--out", str(tmp_path / "b")]) == 0
    sa = json.loads((tmp_path / "a" / "baseline_stats.json").read_text())
    sb = json.loads((tmp_path / "b" / "baseline_stats.json").read_text())
    for key in ("mean", "std", "threshold", "evaluation"):
        assert sa[key] == sb[key]
