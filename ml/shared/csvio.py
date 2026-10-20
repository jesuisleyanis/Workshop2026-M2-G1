"""Format CSV d'échange des fenêtres de features (capture -> entraînement/calibration).

Écrit par `ml.collector.capture` (dans le conteneur collector : stdlib seule, pas de
numpy), lu par `ml.training.dataset.load_csv`. Une ligne = une fenêtre :

    ts,<9 features dans l'ordre de FEATURE_NAMES>,label,missing

`label` = "normal" ou un type de scénario (`service_flood`, ...) ; `missing` = features
absentes de Prometheus (séparateur ";"), mises à 0.0 comme le fait le collector temps réel.
"""

from __future__ import annotations

import csv
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import TextIO

from ml.shared.features import FEATURE_NAMES

CSV_COLUMNS: tuple[str, ...] = ("ts", *FEATURE_NAMES, "label", "missing")

Row = tuple[str, Sequence[float], str, Sequence[str]]


def write_rows(fh: TextIO, rows: Iterable[Row], header: bool = True) -> int:
    """Écrit les lignes dans un flux texte ouvert ; renvoie le nombre de lignes écrites."""
    writer = csv.writer(fh, lineterminator="\n")
    if header:
        writer.writerow(CSV_COLUMNS)
    n = 0
    for ts, vector, label, missing in rows:
        if len(vector) != len(FEATURE_NAMES):
            raise ValueError(f"vecteur de {len(vector)} valeurs, attendu {len(FEATURE_NAMES)}")
        writer.writerow([ts, *(repr(float(v)) for v in vector), label, ";".join(missing)])
        n += 1
    return n


def write_csv(path: Path | str, rows: Iterable[Row], append: bool = False) -> int:
    """Écrit (ou ajoute à) un fichier CSV ; l'en-tête n'est écrit que pour un fichier neuf."""
    path = Path(path)
    header = not (append and path.exists() and path.stat().st_size > 0)
    with path.open("a" if append else "w", newline="", encoding="utf-8") as fh:
        return write_rows(fh, rows, header=header)
