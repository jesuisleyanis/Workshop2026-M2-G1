"""Entraînement sur séries réelles (CSV capturé) : chargement, découpage, calibration, CLI."""

import json
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from ml.shared.csvio import CSV_COLUMNS, write_csv
from ml.shared.features import FEATURE_NAMES
from ml.training.dataset import ATTACK_KINDS, generate_attack, generate_baseline, load_csv
from ml.training.train import HELDOUT_FRACTION, main, model_fingerprint, train

T0 = datetime(2026, 10, 19, 10, 0, tzinfo=timezone.utc)


def iso(i: int, step_s: int = 15, t0: datetime = T0) -> str:
    return (t0 + timedelta(seconds=i * step_s)).isoformat().replace("+00:00", "Z")


def write_series(path, data, label="normal", t0=T0, append=False, missing=()):
    rows = [(iso(i, t0=t0), row, label, missing) for i, row in enumerate(data)]
    return write_csv(path, rows, append=append)


@pytest.fixture()
def baseline_csv(tmp_path):
    path = tmp_path / "baseline_real.csv"
    write_series(path, generate_baseline(1000, seed=5))
    return path


@pytest.fixture()
def attacks_csv(tmp_path):
    path = tmp_path / "attacks_real.csv"
    for k, kind in enumerate(ATTACK_KINDS):
        write_series(path, generate_attack(kind, 12, seed=11 + k), label=kind,
                     t0=T0 + timedelta(hours=2 + k), append=True)
    return path


# --- load_csv ------------------------------------------------------------------

def test_csv_roundtrip_reorders_columns_and_sorts_by_time(tmp_path):
    data = generate_baseline(300, seed=1)
    path = tmp_path / "x.csv"
    rows = [(iso(i), row, "normal", ()) for i, row in enumerate(data)]
    write_csv(path, list(reversed(rows)))  # fichier dans le désordre
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[0].split(",") == list(CSV_COLUMNS)

    series = load_csv(path)
    assert len(series) == 300
    assert list(series.ts) == sorted(series.ts)
    assert np.allclose(series.data, data)


def test_load_csv_rejects_missing_feature_column(tmp_path):
    path = tmp_path / "bad.csv"
    path.write_text("ts," + ",".join(FEATURE_NAMES[:-1]) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="db_errors_per_s"):
        load_csv(path, min_rows=0)


@pytest.mark.parametrize("bad", ["nan", "-1", "abc", "inf"])
def test_load_csv_rejects_invalid_values(tmp_path, bad):
    path = tmp_path / "bad.csv"
    write_series(path, generate_baseline(3, seed=1))
    text = path.read_text(encoding="utf-8").splitlines()
    cells = text[1].split(",")
    cells[1] = bad
    text[1] = ",".join(cells)
    path.write_text("\n".join(text) + "\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_csv(path, min_rows=1)


def test_load_csv_requires_minimum_rows_and_filters_labels(tmp_path, attacks_csv):
    with pytest.raises(ValueError, match="minimum"):
        load_csv(attacks_csv, label="normal")
    flood = load_csv(attacks_csv, min_rows=1, label="service_flood")
    assert len(flood) == 12 and set(flood.labels) == {"service_flood"}


# --- train(real=...) -------------------------------------------------------------

def test_train_on_real_series_uses_chronological_heldout(baseline_csv):
    real = load_csv(baseline_csv)
    model, stats = train(real=real, data_source="baseline_real.csv", n_estimators=50, version="t")
    n_heldout = int(len(real) * HELDOUT_FRACTION)
    assert stats["training"]["n_samples"] == len(real) - n_heldout
    assert stats["training"]["max_samples"] == min(1024, len(real) - n_heldout)
    assert "Prometheus réel" in stats["training"]["data"]
    assert real.ts[-1] in stats["training"]["data"]
    heldout = stats["evaluation"]["normal_heldout"]
    assert heldout["source"].startswith("réel") and heldout["n"] == n_heldout
    assert heldout["false_positive_rate"] <= 0.02


def test_train_reports_real_attacks_separately(baseline_csv, attacks_csv):
    _, stats = train(real=load_csv(baseline_csv), attacks_real=load_csv(attacks_csv, min_rows=1),
                     n_estimators=50, version="t")
    real = stats["evaluation"]["attacks_real"]
    assert set(real) == set(ATTACK_KINDS)
    assert all(r["n"] == 12 and r["score_max"] >= stats["threshold"] for r in real.values())
    assert set(stats["evaluation"]["attacks"]) == set(ATTACK_KINDS)  # simulées toujours là


def test_calibration_overrides_threshold(baseline_csv):
    real = load_csv(baseline_csv)
    model, _ = train(real=real, n_estimators=50, version="t")
    fp = model_fingerprint(model)
    _, stats = train(real=real, n_estimators=50, version="t",
                     calibration={"threshold": 0.58, "model_fingerprint": fp})
    assert stats["threshold"] == 0.58
    assert "calibration" in stats["threshold_source"]
    assert stats["calibration"]["model_fingerprint"] == fp == stats["model_fingerprint"]
    with pytest.raises(ValueError):
        train(real=real, n_estimators=50, calibration={"threshold": 1.5})


def test_fingerprint_is_stable_across_versions_and_changes_with_data(baseline_csv):
    real = load_csv(baseline_csv)
    m1, _ = train(real=real, n_estimators=50, version="1")
    m2, _ = train(real=real, n_estimators=50, version="2")
    m3, _ = train(n_samples=800, n_estimators=50, version="1")
    assert model_fingerprint(m1) == model_fingerprint(m2)
    assert model_fingerprint(m1) != model_fingerprint(m3)


def test_cli_trains_on_real_data(tmp_path, baseline_csv, attacks_csv, capsys):
    calib = tmp_path / "calibration.json"
    calib.write_text(json.dumps({"threshold": 0.61}), encoding="utf-8")
    out = tmp_path / "artifacts"
    rc = main(["--data", str(baseline_csv), "--attack-data", str(attacks_csv),
               "--calibration", str(calib), "--n-estimators", "50", "--version", "9.9.9",
               "--out", str(out)])
    assert rc == 0
    stats = json.loads((out / "baseline_stats.json").read_text())
    assert stats["threshold"] == 0.61 and stats["model_version"] == "9.9.9"
    assert "attacks_real" in stats["evaluation"]
    printed = capsys.readouterr().out
    assert "RÉELLES" in printed and "calibration" in printed
