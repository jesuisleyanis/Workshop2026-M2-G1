"""CLI d'entraînement reproductible de l'IsolationForest.

    python -m ml.training.train --seed 42 --n-samples 20000 --version 1.0.0

Produit (reproductible à seed/version/params égaux) :
    <out>/v<version>/model.joblib          modèle + métadonnées
    <out>/v<version>/baseline_stats.json   moyennes/écarts-types, seuil, évaluation
    <out>/model.joblib, <out>/baseline_stats.json   copie « courante » lue par le detector

Le decideur est le modèle ; les moyennes/écarts-types ne servent qu'à (1) calculer
les z-scores d'explicabilité des `features_top` et (2) un garde-fou statistique
documenté comme tel dans ml/detector.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import sklearn
from sklearn.ensemble import IsolationForest

from ml.shared.features import (
    FEATURE_NAMES,
    STD_FLOOR,
    classify_incident,
    zscores,
)
from ml.training.dataset import ATTACK_KINDS, generate_attack, generate_baseline

DEFAULT_VERSION = "1.0.0"
DEFAULT_OUT = Path(__file__).resolve().parent / "artifacts"

#: Seuil de décision par défaut (contrat §3 : exemple threshold = 0.60). Le seuil
#: effectivement écrit dans baseline_stats.json = max(ce défaut, quantile des scores
#: normaux) pour garantir un taux de faux positifs bas sur la baseline.
DEFAULT_THRESHOLD = 0.60
THRESHOLD_QUANTILE = 0.999

#: Garde-fou statistique (voir ml/detector/README.md) : |z| au-delà duquel on escalade
#: même si le score ML reste sous le seuil. Filet de sécurité contre la dilution du score
#: d'une IsolationForest sur un pic mono-feature, PAS le décideur. Calibré sur les données :
#: max(GUARDRAIL_Z_MIN, GUARDRAIL_FACTOR x plus grand z observé sur la baseline).
GUARDRAIL_Z_MIN = 15.0
GUARDRAIL_FACTOR = 1.5


def anomaly_scores(model: IsolationForest, data: np.ndarray) -> np.ndarray:
    """Score d'anomalie dans (0, 1] : plus haut = plus anormal.

    = -score_samples de scikit-learn, c.-à-d. le s(x, n) = 2^(-E[h(x)]/c(n)) du papier
    original : ~0,5 en zone dense du trafic normal, tend vers 1 pour des points
    très isolés.
    """
    return -model.score_samples(data)


def train(
    n_samples: int = 20000,
    seed: int = 42,
    version: str = DEFAULT_VERSION,
    n_estimators: int = 200,
    max_samples: int | str = 1024,
) -> tuple[IsolationForest, dict]:
    """Entraîne le modèle sur le trafic normal et renvoie (modèle, baseline_stats)."""
    data = generate_baseline(n_samples, seed=seed)
    model = IsolationForest(
        n_estimators=n_estimators,
        max_samples=max_samples,
        contamination="auto",  # le seuil est calibré à part (quantile), pas via contamination
        random_state=seed,
    )
    model.fit(data)

    base_scores = anomaly_scores(model, data)
    threshold = max(DEFAULT_THRESHOLD, float(np.quantile(base_scores, THRESHOLD_QUANTILE)))

    means = {n: float(data[:, i].mean()) for i, n in enumerate(FEATURE_NAMES)}
    stds = {n: float(data[:, i].std(ddof=0)) for i, n in enumerate(FEATURE_NAMES)}

    max_z = max(
        float(((data[:, i] - means[n]) / max(stds[n], STD_FLOOR[n])).max())
        for i, n in enumerate(FEATURE_NAMES)
    )
    guardrail_z = max(GUARDRAIL_Z_MIN, GUARDRAIL_FACTOR * max_z)

    stats = {
        "model_version": version,
        "trained_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "feature_names": list(FEATURE_NAMES),
        "mean": means,
        "std": stds,
        "std_floor": dict(STD_FLOOR),
        "threshold": round(threshold, 4),
        "threshold_quantile": THRESHOLD_QUANTILE,
        "guardrail_z": round(guardrail_z, 2),
        "baseline_max_z": round(max_z, 2),
        "training": {
            "algorithm": "IsolationForest",
            "n_samples": n_samples,
            "seed": seed,
            "n_estimators": n_estimators,
            "max_samples": max_samples,
            "sklearn_version": sklearn.__version__,
            "data": "baseline synthétique (ml/training/dataset.py), trafic normal uniquement",
        },
    }
    stats["evaluation"] = evaluate(model, stats, seed=seed)
    return model, stats


def _max_z(data: np.ndarray, means: dict, stds: dict) -> np.ndarray:
    """Plus grand z-score positif de chaque ligne (vectorisé, même formule que zscores())."""
    mu = np.array([means[n] for n in FEATURE_NAMES])
    sd = np.array([max(stds[n], STD_FLOOR[n]) for n in FEATURE_NAMES])
    return ((data - mu) / sd).max(axis=1)


def evaluate(model: IsolationForest, stats: dict, seed: int = 42, n: int = 2000) -> dict:
    """Mesure sur un jeu normal HELD-OUT + attaques simulées (jamais vues à l'entraînement)."""
    threshold = stats["threshold"]
    means, stds = stats["mean"], stats["std"]

    normal = generate_baseline(n, seed=seed + 10_000)
    normal_scores = anomaly_scores(model, normal)
    report: dict = {
        "normal_heldout": {
            "n": n,
            "score_mean": round(float(normal_scores.mean()), 4),
            "score_p99": round(float(np.quantile(normal_scores, 0.99)), 4),
            "false_positive_rate": round(float((normal_scores >= threshold).mean()), 4),
            "guardrail_false_positive_rate": round(
                float((_max_z(normal, means, stds) >= stats["guardrail_z"]).mean()), 4),
        },
        "attacks": {},
    }
    for kind in ATTACK_KINDS:
        atk = generate_attack(kind, n, seed=seed + 20_000)
        scores = anomaly_scores(model, atk)
        max_z_rows = _max_z(atk, means, stds)
        routed = sum(
            classify_incident(zscores(row, means, stds)).value == kind for row in atk
        )
        report["attacks"][kind] = {
            "n": n,
            "score_mean": round(float(scores.mean()), 4),
            "detection_rate": round(float((scores >= threshold).mean()), 4),  # modèle seul
            "detection_rate_with_guardrail": round(float(
                ((scores >= threshold) | (max_z_rows >= stats["guardrail_z"])).mean()), 4),
            "routing_accuracy": round(routed / n, 4),
        }
    return report


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(model: IsolationForest, stats: dict, out: Path) -> Path:
    """Sérialise dans <out>/v<version>/ et copie en « courant » dans <out>/."""
    version = stats["model_version"]
    vdir = out / f"v{version}"
    vdir.mkdir(parents=True, exist_ok=True)

    model_path = vdir / "model.joblib"
    joblib.dump(
        {
            "model": model,
            "model_version": version,
            "feature_names": list(FEATURE_NAMES),
            "sklearn_version": sklearn.__version__,
        },
        model_path,
    )
    # Le hash permet au detector de refuser un artefact altéré avant de le désérialiser
    # (joblib = pickle : ne jamais charger un fichier non fiable).
    stats["model_sha256"] = _sha256(model_path)
    stats_path = vdir / "baseline_stats.json"
    stats_path.write_text(json.dumps(stats, indent=2, ensure_ascii=False) + "\n")

    shutil.copy2(model_path, out / "model.joblib")
    shutil.copy2(stats_path, out / "baseline_stats.json")
    return vdir


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Entraîne l'IsolationForest RESILIENCE-ALPHA")
    p.add_argument("--n-samples", type=int, default=20000)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--version", default=DEFAULT_VERSION)
    p.add_argument("--n-estimators", type=int, default=200)
    p.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = p.parse_args(argv)

    model, stats = train(args.n_samples, args.seed, args.version, args.n_estimators)
    vdir = save(model, stats, args.out)
    ev = stats["evaluation"]
    sys.stdout.write(
        f"modèle v{args.version} -> {vdir} (seuil={stats['threshold']})\n"
        f"faux positifs (normal held-out): {ev['normal_heldout']['false_positive_rate']:.2%}\n"
    )
    for kind, r in ev["attacks"].items():
        sys.stdout.write(
            f"  {kind:16s} détection modèle={r['detection_rate']:.1%} "
            f"(+garde-fou {r['detection_rate_with_guardrail']:.1%}) routage={r['routing_accuracy']:.1%}\n"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
