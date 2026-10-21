"""Calibration du seuil sur attaques réelles : position du seuil, MTTD, cas non séparable."""

import json
from datetime import timedelta

import numpy as np
import pytest

from ml.training.calibrate import MIN_THRESHOLD, calibrate, main, mttd_seconds, split_runs
from ml.training.dataset import ATTACK_KINDS, generate_attack, generate_baseline, load_csv
from ml.training.tests.test_real_data import T0, write_series
from ml.training.train import (
    EXIT_STALE_CALIBRATION,
    StaleCalibrationError,
    anomaly_scores,
    model_fingerprint,
    save,
    train,
)
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


def test_threshold_sits_between_normal_held_level_and_weakest_model_separable_attack(setup):
    _, normal_csv, attacks_csv, model, stats = setup
    normal, attacks = load_csv(normal_csv), load_csv(attacks_csv, min_rows=1)
    rep = calibrate(model, normal, attacks, margin=0.5, confirm=2, stats=stats)
    floor = rep["normal"]["held_level"]
    by_model = [r for r in rep["attacks"].values() if r["separable"]]
    assert by_model, "au moins un scénario séparable par le modèle"
    weakest = min(r["held_min"] for r in by_model)
    assert max(MIN_THRESHOLD, floor) < rep["threshold"] < weakest
    assert rep["threshold"] == pytest.approx((floor + weakest) / 2, abs=1e-4)
    # le seuil haut (une fenêtre) reste au-dessus du PIC du normal : jamais de faux positif
    if rep["threshold_high"] is not None:
        assert rep["threshold_high"] > rep["normal"]["score_max"]
    assert rep["normal"]["false_positive_rate"] == 0.0
    assert rep["separable"] == all(r["detected_all_runs"] for r in rep["attacks"].values())
    assert rep["model_fingerprint"] == model_fingerprint(model)


def test_mttd_counts_the_ramp_up_windows(setup):
    from ml.training.calibrate import fires, max_z

    _, normal_csv, attacks_csv, model, stats = setup
    attacks = load_csv(attacks_csv, min_rows=1)
    rep = calibrate(model, load_csv(normal_csv), attacks, confirm=2, stats=stats)
    for kind, r in rep["attacks"].items():
        assert r["runs"] == 1 and r["windows"] == 12
        data = attacks.select(kind).data
        hits = fires(anomaly_scores(model, data), rep["threshold"], rep["threshold_high"], 2,
                     max_z(data, stats), stats["guardrail_z"])
        first = int(np.flatnonzero(hits)[0])
        # les 2 fenêtres de montée en charge (normales) ne déclenchent pas
        assert first >= 2, kind
        assert r["mttd_s_worst"] == 15.0 * first, kind
    worst = max(r["mttd_s_worst"] for r in rep["attacks"].values())
    assert calibrate(model, load_csv(normal_csv), attacks, max_mttd_s=worst - 1, confirm=2,
                     stats=stats)["mttd_ok"] is False
    assert calibrate(model, load_csv(normal_csv), attacks, max_mttd_s=worst, confirm=2,
                     stats=stats)["mttd_ok"] is True


def test_guardrail_covers_attacks_the_model_cannot_see(setup):
    # Sans garde-fou, un scénario sous le niveau tenu du normal n'est pas détecté ; avec, il l'est
    # si son signal dépasse guardrail_z (cas réel : db_errors_per_s / waf_blocked_per_s nuls au normal).
    _, normal_csv, attacks_csv, model, stats = setup
    normal, attacks = load_csv(normal_csv), load_csv(attacks_csv, min_rows=1)
    alone = calibrate(model, normal, attacks, confirm=6)
    guarded = calibrate(model, normal, attacks, confirm=6, stats=stats)
    for kind, r in guarded["attacks"].items():
        if not r["separable"]:
            assert alone["attacks"][kind]["detected_all_runs"] is False
            assert r["detected_all_runs"] is True, kind


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


def test_stale_calibration_fails_and_writes_nothing(setup, tmp_path, capsys):
    """Seuil calibré sur un autre modèle : la CLI échoue (code 3) -> le build detector aussi."""
    _, normal_csv, _, _, _ = setup
    calib = tmp_path / "calibration.json"
    calib.write_text(json.dumps({"threshold": 0.6, "model_fingerprint": "périmée"}),
                     encoding="utf-8")
    out = tmp_path / "a"
    rc = train_main(["--data", str(normal_csv), "--n-estimators", "50",
                     "--calibration", str(calib), "--out", str(out)])
    assert rc == EXIT_STALE_CALIBRATION
    assert not (out / "baseline_stats.json").exists()
    assert "make calibrate" in capsys.readouterr().err


def test_allow_stale_calibration_falls_back_to_quantile(setup, tmp_path, capsys):
    _, normal_csv, _, _, _ = setup
    calib = tmp_path / "calibration.json"
    calib.write_text(json.dumps({"threshold": 0.51, "model_fingerprint": "périmée"}),
                     encoding="utf-8")
    out = tmp_path / "a"
    assert train_main(["--data", str(normal_csv), "--n-estimators", "50", "--calibration",
                       str(calib), "--allow-stale-calibration", "--out", str(out)]) == 0
    stats = json.loads((out / "baseline_stats.json").read_text())
    assert stats["threshold"] != 0.51 and "quantile" in stats["threshold_source"]
    assert stats["calibration_ignored"]["calibrated_on"] == "périmée"
    assert "calibration" not in stats
    assert "IGNORÉE" in capsys.readouterr().out


def test_stale_calibration_raises_in_python_api(setup):
    _, normal_csv, _, _, _ = setup
    with pytest.raises(StaleCalibrationError):
        train(real=load_csv(normal_csv), n_estimators=50,
              calibration={"threshold": 0.6, "model_fingerprint": "autre"})


def test_confirmation_rule_matches_the_detector():
    from ml.training.calibrate import fires

    scores = np.array([0.5, 0.75, 0.6, 0.75, 0.76, 0.95, 0.5])
    # 2 fenêtres consécutives >= 0.7, ou une seule >= 0.9 (seuil haut)
    assert fires(scores, 0.7, 0.9, confirm=2).tolist() == [False, False, False, False, True, True, False]
    assert fires(scores, 0.7, None, confirm=1).tolist() == (scores >= 0.7).tolist()


def test_report_carries_high_threshold_and_confirmation(setup):
    _, normal_csv, attacks_csv, model, _ = setup
    rep = calibrate(model, load_csv(normal_csv), load_csv(attacks_csv, min_rows=1), confirm=2)
    weakest = min(r["peak_min"] for r in rep["attacks"].values())
    assert rep["confirm_windows"] == 2
    assert rep["threshold"] < rep["threshold_high"] < weakest
    with pytest.raises(ValueError, match="confirm"):
        calibrate(model, load_csv(normal_csv), load_csv(attacks_csv, min_rows=1), confirm=0)
