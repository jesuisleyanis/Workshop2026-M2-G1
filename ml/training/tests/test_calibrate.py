"""Calibration du seuil sur attaques réelles : position du seuil, MTTD, cas non séparable."""

import json
from datetime import timedelta

import numpy as np
import pytest

from ml.training.calibrate import MIN_THRESHOLD, calibrate, main, mttd_seconds, split_runs
from ml.training.dataset import ATTACK_KINDS, generate_attack, generate_baseline, load_csv
from ml.training.tests.test_real_data import T0, write_series
from ml.training.train import anomaly_scores, model_fingerprint, save, train
from ml.training.train import main as train_main


@pytest.fixture(scope="module")
def setup(tmp_path_factory):
    d = tmp_path_factory.mktemp("calib")
    normal_csv = d / "baseline_real.csv"
    write_series(normal_csv, generate_baseline(1000, seed=5))
    attacks_csv = d / "attacks_real.csv"
    for k, kind in enumerate(ATTACK_KINDS):
        # 2 fenêtres de montée en charge (encore normales) puis l'attaque franche
        ramp = generate_baseline(2, seed=70 + k)
        data = np.vstack([ramp, generate_attack(kind, 10, seed=31 + k)])
        write_series(attacks_csv, data, label=kind, t0=T0 + timedelta(hours=2 + k), append=True)
    model, stats = train(real=load_csv(normal_csv), n_estimators=100, version="c")
    return d, normal_csv, attacks_csv, model, stats


def test_threshold_sits_between_normal_and_weakest_attack(setup):
    _, normal_csv, attacks_csv, model, _ = setup
    normal, attacks = load_csv(normal_csv), load_csv(attacks_csv, min_rows=1)
    rep = calibrate(model, normal, attacks, margin=0.5)
    assert rep["separable"]
    weakest = min(r["peak_min"] for r in rep["attacks"].values())
    floor = max(MIN_THRESHOLD, rep["normal"]["score_p999"])
    assert floor < rep["threshold"] < weakest
    assert rep["threshold"] == pytest.approx((floor + weakest) / 2, abs=1e-4)
    assert rep["normal"]["false_positive_rate"] <= 0.002
    assert rep["model_fingerprint"] == model_fingerprint(model)


def test_mttd_counts_the_ramp_up_windows(setup):
    _, normal_csv, attacks_csv, model, _ = setup
    attacks = load_csv(attacks_csv, min_rows=1)
    rep = calibrate(model, load_csv(normal_csv), attacks)
    for kind, r in rep["attacks"].items():
        assert r["runs"] == 1 and r["windows"] == 12
        scores = anomaly_scores(model, attacks.select(kind).data)
        first = int(np.flatnonzero(scores >= rep["threshold"])[0])
        # les 2 fenêtres de montée en charge (normales) ne déclenchent pas : MTTD >= 30 s
        assert first >= 2, kind
        assert r["mttd_s_worst"] == 15.0 * first, kind
    worst = max(r["mttd_s_worst"] for r in rep["attacks"].values())
    assert rep["mttd_ok"] is False  # >= 30 s > budget par défaut de 20 s
    assert calibrate(model, load_csv(normal_csv), attacks, max_mttd_s=worst)["mttd_ok"] is True


def test_split_runs_and_mttd_helpers(setup):
    _, _, attacks_csv, model, _ = setup
    flood = load_csv(attacks_csv, min_rows=1, label="service_flood")
    (times, data), = split_runs(flood)
    assert len(times) == 12
    scores = anomaly_scores(model, data)
    assert mttd_seconds(times, scores, threshold=2.0) is None  # jamais atteint
    assert mttd_seconds(times, scores, threshold=0.0) == 0.0


def test_not_separable_writes_nothing(setup, tmp_path):
    _, normal_csv, _, model, stats = setup
    # « attaque » qui ressemble au normal : le modèle ne peut pas la séparer
    weak = tmp_path / "weak.csv"
    write_series(weak, generate_baseline(10, seed=123), label="service_flood")
    model_dir = tmp_path / "artifacts"
    save(model, dict(stats), model_dir)
    out = tmp_path / "calibration.json"
    rc = main(["--normal", str(normal_csv), "--attacks", str(weak),
               "--model-dir", str(model_dir), "--out", str(out)])
    assert rc == 1 and not out.exists()
    report = json.loads((tmp_path / "calibration.report.json").read_text(encoding="utf-8"))
    assert report["separable"] is False and report["threshold"] is None
    assert report["attacks"]["service_flood"]["separable"] is False  # le coupable est nommé


def test_cli_end_to_end_calibrate_then_retrain(setup, tmp_path, capsys):
    _, normal_csv, attacks_csv, _, _ = setup
    model_dir = tmp_path / "artifacts"
    assert train_main(["--data", str(normal_csv), "--n-estimators", "100", "--version", "c",
                       "--out", str(model_dir)]) == 0
    out = tmp_path / "calibration.json"
    rc = main(["--normal", str(normal_csv), "--attacks", str(attacks_csv),
               "--model-dir", str(model_dir), "--out", str(out), "--max-mttd", "180"])
    assert rc == 0
    calib = json.loads(out.read_text(encoding="utf-8"))
    assert calib["separable"] and calib["model_version"] == "c"
    assert all(r["separable"] for r in calib["attacks"].values())
    assert (tmp_path / "calibration.report.json").exists()

    # ré-entraînement avec la calibration : même modèle -> pas d'alerte d'empreinte
    capsys.readouterr()
    assert train_main(["--data", str(normal_csv), "--n-estimators", "100", "--version", "c2",
                       "--calibration", str(out), "--out", str(model_dir)]) == 0
    printed = capsys.readouterr().out
    assert "ATTENTION" not in printed
    stats = json.loads((model_dir / "baseline_stats.json").read_text())
    assert stats["threshold"] == calib["threshold"]


def test_retrain_with_stale_calibration_warns(setup, tmp_path, capsys):
    _, normal_csv, _, _, _ = setup
    calib = tmp_path / "calibration.json"
    calib.write_text(json.dumps({"threshold": 0.6, "model_fingerprint": "périmée"}),
                     encoding="utf-8")
    train_main(["--data", str(normal_csv), "--n-estimators", "50", "--calibration", str(calib),
                "--out", str(tmp_path / "a")])
    assert "ATTENTION" in capsys.readouterr().out
