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

Persistance (fenêtres courtes de 5 s, un vecteur/s) : le normal a des pics BREFS, une attaque
dure. Le detector ne déclare l'anomalie que si le score tient au-dessus du seuil sur `confirm`
fenêtres CONSÉCUTIVES (ou dépasse d'un coup `threshold_high`). La calibration raisonne donc sur
le « niveau tenu » : max, sur toutes les positions, du minimum de `confirm` scores consécutifs.
  - plancher = niveau tenu du normal ; un scénario est séparable PAR LE MODÈLE si le niveau tenu
    de chacun de ses passages le dépasse ; seuil = plancher + margin x (plus faible de ces niveaux) ;
  - un scénario invisible pour le modèle (signal nul dans tout le normal : `db_errors_per_s`,
    `waf_blocked_per_s` — une IsolationForest ne coupe jamais sur une variable constante) est
    accepté s'il est COUVERT PAR LE GARDE-FOU statistique (z >= guardrail_z) sur chaque passage ;
  - faux positifs et MTTD sont mesurés avec la règle complète du detector (modèle + garde-fou).

Codes retour : 0 = séparable et MTTD respecté ; 1 = attaques non séparables du normal
(calibration.json n'est PAS écrit, seul le rapport l'est) ; 2 = seuil écrit mais un
scénario dépasse --max-mttd.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from ml.shared.features import zscores
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
#: Fenêtres consécutives au-dessus du seuil pour confirmer une anomalie (cf. docstring) :
#: captures du 21/10 (pas 1 s) : 4 sépare flood et auth_abuse du normal avec marge.
DEFAULT_CONFIRM = 4
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


def fires(scores: np.ndarray, threshold: float | None, threshold_high: float | None = None,
          confirm: int = 1, z: np.ndarray | None = None,
          guardrail_z: float | None = None) -> np.ndarray:
    """Fenêtres où le detector déclare l'anomalie (même logique que ml.detector.core) :
    modèle confirmé sur `confirm` fenêtres, ou seuil haut, ou garde-fou (z max >= guardrail_z)."""
    out = np.zeros(len(scores), dtype=bool)
    run = 0
    for i, s in enumerate(scores):
        run = run + 1 if threshold is not None and s >= threshold else 0
        out[i] = (run >= confirm or (threshold_high is not None and s >= threshold_high)
                  or (z is not None and guardrail_z is not None and z[i] >= guardrail_z))
    return out


def held_level(scores: np.ndarray, confirm: int) -> float:
    """Niveau tenu sur `confirm` fenêtres consécutives (max des minima glissants)."""
    if len(scores) < confirm:
        return float("-inf")
    return float(max(scores[i:i + confirm].min() for i in range(len(scores) - confirm + 1)))


def max_z(data: np.ndarray, stats: dict) -> np.ndarray:
    """z-score maximal (vers le haut) de chaque fenêtre vs la baseline du modèle."""
    return np.array([max(zscores(list(v), stats["mean"], stats["std"]).values()) for v in data])


def mttd_seconds(times: list[datetime], scores: np.ndarray, threshold: float | None,
                 threshold_high: float | None = None, confirm: int = 1,
                 z: np.ndarray | None = None, guardrail_z: float | None = None) -> float | None:
    """Délai entre la 1re fenêtre capturée du passage et la 1re fenêtre >= seuil.

    C'est le temps de détection côté MODÈLE (résolution = le pas de capture) ; la
    latence de la chaîne (scrape, collecte, relève du detector) s'y ajoute en démo.
    """
    hits = np.flatnonzero(fires(scores, threshold, threshold_high, confirm, z, guardrail_z))
    if not len(hits):
        return None
    return (times[hits[0]] - times[0]).total_seconds()


def calibrate(model, normal: Series, attacks: Series, margin: float = DEFAULT_MARGIN,
              max_mttd_s: float = DEFAULT_MAX_MTTD_S, confirm: int = DEFAULT_CONFIRM,
              stats: dict | None = None) -> dict:
    """Calcule le seuil et le rapport de calibration (voir docstring du module).

    `stats` (baseline_stats du modèle) active le garde-fou dans l'évaluation ; sans lui, seul le
    modèle compte (un scénario invisible pour le modèle rend alors la calibration non séparable).
    """
    if not 0.0 < margin < 1.0:
        raise ValueError("margin doit être dans ]0, 1[")
    if confirm < 1:
        raise ValueError("confirm doit être >= 1")
    guardrail_z = float(stats["guardrail_z"]) if stats else None
    normal_scores = anomaly_scores(model, normal.data)
    normal_z = max_z(normal.data, stats) if stats else None
    floor = max(MIN_THRESHOLD, held_level(normal_scores, confirm))

    per_kind: dict[str, dict] = {}
    for kind in ATTACK_KINDS:
        subset = attacks.select(kind)
        if not len(subset):
            continue
        runs = [(times, anomaly_scores(model, data), max_z(data, stats) if stats else None)
                for times, data in split_runs(subset)]
        per_kind[kind] = {"runs": runs, "held_min": min(held_level(s, confirm) for _, s, _ in runs)}
    if not per_kind:
        raise ValueError("aucune fenêtre d'attaque étiquetée avec un type connu "
                         f"({', '.join(ATTACK_KINDS)})")

    model_kinds = [k for k in per_kind.values() if k["held_min"] > floor]
    threshold = threshold_high = None
    if model_kinds:
        attack_lo = min(k["held_min"] for k in model_kinds)
        threshold = round(floor + margin * (attack_lo - floor), 4)
        # Seuil haut (une seule fenêtre suffit) : au-dessus du PIC du normal, sous le plus faible
        # pic des attaques que le modèle sépare ; absent si aucune attaque ne dépasse ce pic.
        normal_peak = float(normal_scores.max())
        peak_lo = min(float(s.max()) for k in model_kinds for _, s, _ in k["runs"])
        if peak_lo > normal_peak:
            threshold_high = round(normal_peak + margin * (peak_lo - normal_peak), 4)

    report: dict = {
        "separable": False,
        "threshold": threshold,
        "threshold_high": threshold_high,
        "confirm_windows": confirm,
        "guardrail_z": guardrail_z,
        "margin": margin,
        "normal": {
            "n": len(normal),
            "score_p999": round(float(np.quantile(normal_scores, THRESHOLD_QUANTILE)), 4),
            "score_max": round(float(normal_scores.max()), 4),
            "held_level": round(floor, 4),
            "false_positive_rate": round(float(fires(
                normal_scores, threshold, threshold_high, confirm, normal_z, guardrail_z).mean()), 4),
        },
        "attacks": {},
        "max_mttd_s": max_mttd_s,
        "mttd_ok": False,
        "model_fingerprint": model_fingerprint(model),
        "calibrated_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    all_detected, mttd_ok = threshold is not None, True
    for kind, k in per_kind.items():
        mttds = [mttd_seconds(t, s, threshold, threshold_high, confirm, z, guardrail_z)
                 for t, s, z in k["runs"]]
        detected = None not in mttds
        worst = max(mttds) if detected else None
        all_detected = all_detected and detected
        mttd_ok = mttd_ok and detected and worst <= max_mttd_s
        report["attacks"][kind] = {
            # séparable PAR LE MODÈLE : niveau tenu de chaque passage au-dessus du normal
            "separable": k["held_min"] > floor,
            # sinon couvert par le garde-fou statistique ? (règle complète du detector)
            "detected_all_runs": detected,
            "runs": len(k["runs"]),
            "windows": sum(len(s) for _, s, _ in k["runs"]),
            "peak_min": round(min(float(s.max()) for _, s, _ in k["runs"]), 4),
            "held_min": round(k["held_min"], 4),
            "mttd_s_worst": worst,
        }
    report["separable"] = all_detected and report["normal"]["false_positive_rate"] == 0.0
    report["mttd_ok"] = report["separable"] and mttd_ok
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
                       load_csv(args.attacks, min_rows=1), args.margin, args.max_mttd, args.confirm,
                       stats=loaded.stats)
    report["model_version"] = loaded.version
    report["data"] = {"normal": args.normal.name, "attacks": args.attacks.name}

    n = report["normal"]
    sys.stdout.write(f"normal : n={n['n']} max={n['score_max']} niveau tenu ({report['confirm_windows']} "
                     f"fenêtres)={n['held_level']} faux positifs={n['false_positive_rate']}\n")
    for kind, r in report["attacks"].items():
        how = ("modèle" if r["separable"] else
               "garde-fou" if r["detected_all_runs"] else "NON DÉTECTÉ sur au moins un passage")
        sys.stdout.write(f"  {kind:16s} passages={r['runs']} niveau tenu min={r['held_min']} "
                         f"MTTD pire={r['mttd_s_worst']} s  <- {how}\n")
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
