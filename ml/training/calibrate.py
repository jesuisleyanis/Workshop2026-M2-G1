"""Calibration du seuil de décision sur les VRAIES attaques (et mesure du MTTD).

    python -m ml.training.calibrate \\
        --normal ml/training/data/baseline_real.csv \\
        --attacks ml/training/data/attacks_real.csv \\
        [--model-dir ml/training/artifacts] [--margin 0.5] [--max-mttd 20] \\
        [--out ml/training/data/calibration.json]

Entrées : le modèle entraîné sur la baseline réelle (`ml.training.train --data`), les
fenêtres normales réelles et les fenêtres capturées pendant chaque scénario
(`ml.collector.capture --label <scenario>`).

Règle : le seuil doit être AU-DESSUS du normal (quantile 99,9 % des scores normaux)
et AU-DESSOUS du pic le plus faible des attaques (pic minimal sur tous les passages de
tous les scénarios). On le place à `margin` (0,5 = milieu) entre les deux. Le seuil
reste celui du MODÈLE (R8) : la calibration ne fait que choisir où couper son score.

Le fichier écrit (calibration.json, versionné) est relu par `train --calibration` et
par le build du detector : le seuil survit au ré-entraînement tant que l'empreinte du
modèle (`model_fingerprint`) est la même.

Le rapport complet est TOUJOURS écrit à côté (`calibration.report.json`), même en échec :
c'est lui qu'on lit pour savoir quel scénario ne se détache pas du normal.

Confirmation (anti faux positif, fenêtres courtes) : le detector ne déclare l'anomalie que si
le score dépasse le seuil sur `confirm` fenêtres CONSÉCUTIVES, ou dépasse d'un coup le
`threshold_high` (milieu entre le seuil et le pic le plus faible des attaques). Les deux
valeurs sont calculées ici et le MTTD / taux de faux positifs sont mesurés avec cette règle.

Codes retour : 0 = séparable et MTTD respecté ; 1 = attaques non séparables du normal
(calibration.json n'est PAS écrit, seul le rapport l'est) ; 2 = seuil écrit mais un
scénario dépasse --max-mttd.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from ml.training.dataset import ATTACK_KINDS, Series, load_csv
from ml.training.train import DEFAULT_OUT, THRESHOLD_QUANTILE, anomaly_scores, model_fingerprint

DEFAULT_DATA = Path(__file__).resolve().parent / "data"

#: Plancher du seuil : ~0,5 = zone dense du trafic normal pour une IsolationForest ;
#: couper en dessous reviendrait à déclarer anormale la moitié du normal.
MIN_THRESHOLD = 0.5
DEFAULT_MARGIN = 0.5
#: Budget de détection (fenêtres) dans les 60 s de la démo : le reste va à la
#: remédiation et à verify_tx.
DEFAULT_MAX_MTTD_S = 20.0
#: Fenêtres consécutives au-dessus du seuil pour confirmer une anomalie (cf. docstring).
DEFAULT_CONFIRM = 2
#: Deux fenêtres d'un même label séparées de plus que ça = deux passages distincts.
RUN_GAP_S = 60.0


def _parse_ts(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def split_runs(series: Series, gap_s: float = RUN_GAP_S) -> list[tuple[list[datetime], np.ndarray]]:
    """Découpe une série d'un même label en passages (trous > gap_s)."""
    runs: list[tuple[list[datetime], list[int]]] = []
    prev: datetime | None = None
    for i, ts in enumerate(series.ts):
        t = _parse_ts(ts)
        if prev is None or (t - prev).total_seconds() > gap_s:
            runs.append(([], []))
        runs[-1][0].append(t)
        runs[-1][1].append(i)
        prev = t
    return [(times, series.data[idx]) for times, idx in runs]


def fires(scores: np.ndarray, threshold: float, threshold_high: float | None = None,
          confirm: int = 1) -> np.ndarray:
    """Fenêtres où la règle du detector déclare l'anomalie (même logique que ml.detector.core)."""
    out = np.zeros(len(scores), dtype=bool)
    run = 0
    for i, s in enumerate(scores):
        run = run + 1 if s >= threshold else 0
        out[i] = run >= confirm or (threshold_high is not None and s >= threshold_high)
    return out


def mttd_seconds(times: list[datetime], scores: np.ndarray, threshold: float,
                 threshold_high: float | None = None, confirm: int = 1) -> float | None:
    """Délai entre la 1re fenêtre capturée du passage et la 1re fenêtre >= seuil.

    C'est le temps de détection côté MODÈLE (résolution = le pas de capture) ; la
    latence de la chaîne (scrape, collecte, relève du detector) s'y ajoute en démo.
    """
    hits = np.flatnonzero(fires(scores, threshold, threshold_high, confirm))
    if not len(hits):
        return None
    return (times[hits[0]] - times[0]).total_seconds()


def calibrate(model, normal: Series, attacks: Series, margin: float = DEFAULT_MARGIN,
              max_mttd_s: float = DEFAULT_MAX_MTTD_S, confirm: int = DEFAULT_CONFIRM) -> dict:
    """Calcule le seuil et le rapport de calibration (voir docstring du module)."""
    if not 0.0 < margin < 1.0:
        raise ValueError("margin doit être dans ]0, 1[")
    if confirm < 1:
        raise ValueError("confirm doit être >= 1")
    normal_scores = anomaly_scores(model, normal.data)
    normal_hi = float(np.quantile(normal_scores, THRESHOLD_QUANTILE))

    per_kind: dict[str, dict] = {}
    for kind in ATTACK_KINDS:
        subset = attacks.select(kind)
        if not len(subset):
            continue
        runs = [(times, anomaly_scores(model, data)) for times, data in split_runs(subset)]
        per_kind[kind] = {"runs": runs, "peak_min": min(float(s.max()) for _, s in runs)}
    if not per_kind:
        raise ValueError("aucune fenêtre d'attaque étiquetée avec un type connu "
                         f"({', '.join(ATTACK_KINDS)})")

    attack_lo = min(k["peak_min"] for k in per_kind.values())
    floor = max(MIN_THRESHOLD, normal_hi)
    separable = attack_lo > floor
    threshold = round(floor + margin * (attack_lo - floor), 4) if separable else None
    threshold_high = round((threshold + attack_lo) / 2, 4) if separable else None

    report: dict = {
        "separable": separable,
        "threshold": threshold,
        "threshold_high": threshold_high,
        "confirm_windows": confirm,
        "margin": margin,
        "normal": {
            "n": len(normal),
            "score_p999": round(normal_hi, 4),
            "score_max": round(float(normal_scores.max()), 4),
            "false_positive_rate": (
                round(float(fires(normal_scores, threshold, threshold_high, confirm).mean()), 4)
                if separable else None),
        },
        "attacks": {},
        "max_mttd_s": max_mttd_s,
        "mttd_ok": False,
        "model_fingerprint": model_fingerprint(model),
        "calibrated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    mttd_ok = separable
    for kind, k in per_kind.items():
        mttds = [mttd_seconds(t, s, threshold, threshold_high, confirm) if separable else None
                 for t, s in k["runs"]]
        worst = None if None in mttds else max(mttds)
        mttd_ok = mttd_ok and worst is not None and worst <= max_mttd_s
        report["attacks"][kind] = {
            # sous le plancher : ce scénario ne se détache pas du normal (cause d'un échec)
            "separable": k["peak_min"] > floor,
            "runs": len(k["runs"]),
            "windows": sum(len(s) for _, s in k["runs"]),
            "peak_min": round(k["peak_min"], 4),
            "mttd_s_worst": worst,
        }
    report["mttd_ok"] = mttd_ok
    return report


def main(argv: list[str] | None = None) -> int:
    from ml.detector.model import load_model  # vérifie le sha256 avant de désérialiser

    p = argparse.ArgumentParser(description="Calibre le seuil sur les attaques réelles")
    p.add_argument("--normal", type=Path, default=DEFAULT_DATA / "baseline_real.csv")
    p.add_argument("--attacks", type=Path, default=DEFAULT_DATA / "attacks_real.csv")
    p.add_argument("--model-dir", type=Path, default=DEFAULT_OUT)
    p.add_argument("--margin", type=float, default=DEFAULT_MARGIN)
    p.add_argument("--max-mttd", type=float, default=DEFAULT_MAX_MTTD_S)
    p.add_argument("--confirm", type=int, default=DEFAULT_CONFIRM,
                   help="fenêtres consécutives au-dessus du seuil pour confirmer (detector)")
    p.add_argument("--out", type=Path, default=DEFAULT_DATA / "calibration.json")
    args = p.parse_args(argv)

    loaded = load_model(args.model_dir)
    report = calibrate(loaded.model, load_csv(args.normal, label="normal"),
                       load_csv(args.attacks, min_rows=1), args.margin, args.max_mttd, args.confirm)
    report["model_version"] = loaded.version
    report["data"] = {"normal": args.normal.name, "attacks": args.attacks.name}

    n = report["normal"]
    sys.stdout.write(f"normal : n={n['n']} p99.9={n['score_p999']} max={n['score_max']}\n")
    for kind, r in report["attacks"].items():
        sys.stdout.write(f"  {kind:16s} passages={r['runs']} pic min={r['peak_min']} "
                         f"MTTD pire={r['mttd_s_worst']} s"
                         f"{'' if r['separable'] else '  <- NON SÉPARABLE'}\n")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    report_path = args.out.with_name(args.out.stem + ".report.json")
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    sys.stdout.write(f"rapport -> {report_path}\n")
    if not report["separable"]:
        sys.stdout.write(f"NON SÉPARABLE : rien n'est écrit dans {args.out.name}.\n"
                         "-> capturer plus de normal varié / revoir le scénario (jamais de if en dur, R8)\n")
        return 1
    args.out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    sys.stdout.write(f"seuil calibré = {report['threshold']} -> {args.out}\n"
                     "-> ré-entraîner avec --calibration (ou rebuild du detector)\n")
    if not report["mttd_ok"]:
        sys.stdout.write(f"ATTENTION : MTTD > {args.max_mttd} s ou attaque non détectée sur un passage\n")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
