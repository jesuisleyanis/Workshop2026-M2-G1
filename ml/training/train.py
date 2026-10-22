"""CLI d'entraînement reproductible de l'IsolationForest.

    python -m ml.training.train --seed 42 --n-samples 20000 --version 1.0.0      # synthétique
    python -m ml.training.train --data ml/training/data/baseline_real.csv \\
        [--attack-data ml/training/data/attacks_real.csv] \\
        [--calibration ml/training/data/calibration.json] --version 1.1.0       # réel

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
from datetime import UTC, datetime
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
from ml.training.dataset import (
    ATTACK_KINDS,
    Series,
    generate_attack,
    generate_baseline,
    load_csv,
)

DEFAULT_VERSION = "1.0.0"

#: Part des fenêtres réelles gardées pour l'évaluation : les plus RÉCENTES (découpage
#: chronologique, pas aléatoire — deux fenêtres voisines sont autocorrélées et un
#: tirage aléatoire mettrait des quasi-doublons des deux côtés).
HELDOUT_FRACTION = 0.2
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


class StaleCalibrationError(RuntimeError):
    """calibration.json a été calculée sur un autre modèle que celui qu'on entraîne."""


#: Code retour de la CLI quand la calibration est périmée (fait échouer le build detector).
EXIT_STALE_CALIBRATION = 3


def model_fingerprint(model: IsolationForest) -> str:
    """Empreinte du COMPORTEMENT du modèle (scores sur un jeu sonde fixe).

    Contrairement au sha256 de model.joblib (qui change avec la version écrite dedans),
    elle est identique pour deux entraînements équivalents (mêmes données, seed,
    hyperparamètres, scikit-learn) : c'est ce qui dit si un seuil calibré reste valable.
    """
    probe = np.vstack([generate_baseline(64, seed=0)]
                      + [generate_attack(k, 16, seed=0) for k in ATTACK_KINDS])
    scores = np.round(anomaly_scores(model, probe), 6)
    return hashlib.sha256(scores.tobytes()).hexdigest()[:16]


def train(
    n_samples: int = 20000,
    seed: int = 42,
    version: str = DEFAULT_VERSION,
    n_estimators: int = 200,
    max_samples: int | str = 1024,
    real: Series | None = None,
    data_source: str | None = None,
    attacks_real: Series | None = None,
    calibration: dict | None = None,
    allow_stale_calibration: bool = False,
) -> tuple[IsolationForest, dict]:
    """Entraîne le modèle sur le trafic normal et renvoie (modèle, baseline_stats).

    `real` (fenêtres Prometheus capturées) remplace la baseline synthétique : on
    entraîne sur les (1 - HELDOUT_FRACTION) plus anciennes, on évalue sur les plus
    récentes. `attacks_real` (fenêtres capturées pendant `make attack`, étiquetées)
    s'ajoute à l'évaluation. `calibration` (sortie de ml.training.calibrate) impose
    le seuil calibré sur les vraies attaques à la place du quantile.

    Lève StaleCalibrationError si `calibration` a été calculée sur un autre modèle
    (`model_fingerprint` différente), sauf `allow_stale_calibration` : la calibration
    est alors ignorée et le seuil reste celui du quantile.
    """
    heldout = None
    if real is not None:
        n_train = len(real) - max(1, int(len(real) * HELDOUT_FRACTION))
        data, heldout = real.data[:n_train], real.data[n_train:]
        n_samples = n_train
        if isinstance(max_samples, int):
            max_samples = min(max_samples, n_train)
        data_desc = (f"Prometheus réel ({data_source or 'csv'}) : {len(real)} fenêtres "
                     f"{real.ts[0]} -> {real.ts[-1]}, held-out = {len(heldout)} plus récentes")
    else:
        data = generate_baseline(n_samples, seed=seed)
        data_desc = "baseline synthétique (ml/training/dataset.py), trafic normal uniquement"

    model = IsolationForest(
        n_estimators=n_estimators,
        max_samples=max_samples,
        contamination="auto",  # le seuil est calibré à part (quantile), pas via contamination
        random_state=seed,
    )
    model.fit(data)

    fingerprint = model_fingerprint(model)
    calibration_ignored = None
    calibrated_on = (calibration or {}).get("model_fingerprint")
    if calibrated_on is not None and calibrated_on != fingerprint:
        # Seuil calculé pour un AUTRE modèle (données, seed ou scikit-learn différents) :
        # l'appliquer en silence donnerait un detector mal réglé. On échoue, sauf demande
        # explicite, auquel cas on retombe sur le seuil par quantile (jamais le seuil périmé).
        if not allow_stale_calibration:
            raise StaleCalibrationError(
                f"calibration faite sur le modèle {calibrated_on}, modèle entraîné = {fingerprint} "
                "(données, seed ou scikit-learn différents) : relancer `make calibrate`")
        calibration_ignored = {"calibrated_on": calibrated_on, "reason": "empreinte différente"}
        calibration = None

    base_scores = anomaly_scores(model, data)
    threshold = max(DEFAULT_THRESHOLD, float(np.quantile(base_scores, THRESHOLD_QUANTILE)))
    threshold_source = f"max({DEFAULT_THRESHOLD}, quantile {THRESHOLD_QUANTILE} baseline)"
    if calibration is not None:
        threshold = float(calibration["threshold"])
        if not 0.0 < threshold < 1.0:
            raise ValueError(f"seuil calibré hors de ]0, 1[ : {threshold}")
        threshold_source = "calibration sur attaques réelles (ml.training.calibrate)"

    means = {n: float(data[:, i].mean()) for i, n in enumerate(FEATURE_NAMES)}
    stds = {n: float(data[:, i].std(ddof=0)) for i, n in enumerate(FEATURE_NAMES)}

    max_z = max(
        float(((data[:, i] - means[n]) / max(stds[n], STD_FLOOR[n])).max())
        for i, n in enumerate(FEATURE_NAMES)
    )
    guardrail_z = max(GUARDRAIL_Z_MIN, GUARDRAIL_FACTOR * max_z)

    stats = {
        "model_version": version,
        "trained_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "feature_names": list(FEATURE_NAMES),
        "mean": means,
        "std": stds,
        "std_floor": dict(STD_FLOOR),
        "threshold": round(threshold, 4),
        "threshold_quantile": THRESHOLD_QUANTILE,
        "threshold_source": threshold_source,
        "guardrail_z": round(guardrail_z, 2),
        "baseline_max_z": round(max_z, 2),
        "training": {
            "algorithm": "IsolationForest",
            "n_samples": n_samples,
            "seed": seed,
            "n_estimators": n_estimators,
            "max_samples": max_samples,
            "sklearn_version": sklearn.__version__,
            "data": data_desc,
        },
    }
    stats["model_fingerprint"] = fingerprint
    if calibration is not None:
        stats["calibration"] = calibration
    if calibration_ignored is not None:
        stats["calibration_ignored"] = calibration_ignored
    stats["evaluation"] = evaluate(model, stats, seed=seed, normal_heldout=heldout,
                                   attacks_real=attacks_real)
    return model, stats


def _max_z(data: np.ndarray, means: dict, stds: dict) -> np.ndarray:
    """Plus grand z-score positif de chaque ligne (vectorisé, même formule que zscores())."""
    mu = np.array([means[n] for n in FEATURE_NAMES])
    sd = np.array([max(stds[n], STD_FLOOR[n]) for n in FEATURE_NAMES])
    return ((data - mu) / sd).max(axis=1)


def _attack_report(model: IsolationForest, stats: dict, kind: str, atk: np.ndarray) -> dict:
    threshold = stats["threshold"]
    scores = anomaly_scores(model, atk)
    max_z_rows = _max_z(atk, stats["mean"], stats["std"])
    routed = sum(
        classify_incident(zscores(row, stats["mean"], stats["std"])).value == kind for row in atk
    )
    n = len(atk)
    return {
        "n": n,
        "score_mean": round(float(scores.mean()), 4),
        "score_max": round(float(scores.max()), 4),
        "detection_rate": round(float((scores >= threshold).mean()), 4),  # modèle seul
        "detection_rate_with_guardrail": round(float(
            ((scores >= threshold) | (max_z_rows >= stats["guardrail_z"])).mean()), 4),
        "routing_accuracy": round(routed / n, 4),
    }


def evaluate(model: IsolationForest, stats: dict, seed: int = 42, n: int = 2000,
             normal_heldout: np.ndarray | None = None,
             attacks_real: Series | None = None) -> dict:
    """Mesure sur un jeu normal HELD-OUT + attaques (jamais vus à l'entraînement).

    `attacks` = attaques SIMULÉES (indicatif : séparation entre nos deux simulations) ;
    `attacks_real` = fenêtres capturées pendant les vrais scénarios, quand fournies.
    Sur une attaque réelle, `detection_rate` porte sur TOUTES les fenêtres capturées,
    montée en charge comprise : c'est `score_max` qui dit si l'attaque est vue.
    """
    threshold = stats["threshold"]
    means, stds = stats["mean"], stats["std"]

    normal = normal_heldout if normal_heldout is not None else generate_baseline(n, seed=seed + 10_000)
    normal_scores = anomaly_scores(model, normal)
    report: dict = {
        "normal_heldout": {
            "source": "réel (fenêtres les plus récentes)" if normal_heldout is not None else "synthétique",
            "n": len(normal),
            "score_mean": round(float(normal_scores.mean()), 4),
            "score_p99": round(float(np.quantile(normal_scores, 0.99)), 4),
            "false_positive_rate": round(float((normal_scores >= threshold).mean()), 4),
            "guardrail_false_positive_rate": round(
                float((_max_z(normal, means, stds) >= stats["guardrail_z"]).mean()), 4),
        },
        "attacks": {},
    }
    for kind in ATTACK_KINDS:
        report["attacks"][kind] = _attack_report(
            model, stats, kind, generate_attack(kind, n, seed=seed + 20_000))
    if attacks_real is not None:
        report["attacks_real"] = {
            kind: _attack_report(model, stats, kind, subset.data)
            for kind in ATTACK_KINDS
            if len(subset := attacks_real.select(kind))
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
    p.add_argument("--data", type=Path,
                   help="CSV de trafic NORMAL réel (ml.collector.capture) ; défaut : synthétique")
    p.add_argument("--attack-data", type=Path,
                   help="CSV de fenêtres capturées pendant les scénarios (label = type)")
    p.add_argument("--calibration", type=Path,
                   help="calibration.json (ml.training.calibrate) : impose le seuil calibré")
    p.add_argument("--allow-stale-calibration", action="store_true",
                   help="si la calibration vise un autre modèle : l'ignorer (seuil par quantile) "
                        "au lieu d'échouer")
    args = p.parse_args(argv)

    real = load_csv(args.data, label="normal") if args.data else None
    attacks = load_csv(args.attack_data, min_rows=1) if args.attack_data else None
    calibration = json.loads(args.calibration.read_text(encoding="utf-8")) if args.calibration else None

    try:
        model, stats = train(args.n_samples, args.seed, args.version, args.n_estimators,
                             real=real, data_source=args.data.name if args.data else None,
                             attacks_real=attacks, calibration=calibration,
                             allow_stale_calibration=args.allow_stale_calibration)
    except StaleCalibrationError as exc:
        sys.stderr.write(f"ERREUR : {exc}\n"
                         "(rien n'est écrit ; --allow-stale-calibration pour ignorer la calibration)\n")
        return EXIT_STALE_CALIBRATION
    vdir = save(model, stats, args.out)
    ev = stats["evaluation"]
    sys.stdout.write(
        f"modèle v{args.version} -> {vdir} (seuil={stats['threshold']}, {stats['threshold_source']})\n"
        f"données : {stats['training']['data']}\n"
        f"faux positifs (normal held-out {ev['normal_heldout']['source']}): "
        f"{ev['normal_heldout']['false_positive_rate']:.2%}\n"
    )
    if "calibration_ignored" in stats:
        sys.stdout.write("ATTENTION : calibration IGNORÉE (faite sur un autre modèle) -> seuil par "
                         "quantile ; relancer `make calibrate`\n")
    for section, title in (("attacks", "attaques simulées (indicatif)"),
                           ("attacks_real", "attaques RÉELLES capturées")):
        if section not in ev:
            continue
        sys.stdout.write(f"{title} :\n")
        for kind, r in ev[section].items():
            sys.stdout.write(
                f"  {kind:16s} détection modèle={r['detection_rate']:.1%} "
                f"(+garde-fou {r['detection_rate_with_guardrail']:.1%}) score max={r['score_max']} "
                f"routage={r['routing_accuracy']:.1%}\n"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
