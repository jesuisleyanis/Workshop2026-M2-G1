"""Données d'entraînement : séries RÉELLES capturées (CSV) ou dataset simulé.

`load_csv` charge les fenêtres capturées sur Prometheus par `ml.collector.capture`
(format : `ml.shared.csvio`). C'est la source à utiliser avant le jury.

Le reste du module est la génération programmatique (trafic normal simulé + attaques simulées).

Le modèle est NON supervisé : il n'est entraîné que sur du trafic normal
(`generate_baseline`). Les attaques (`generate_attack`) ne servent qu'à ÉVALUER le
modèle (taux de détection) et à tester la chaîne — elles ne sont jamais vues à
l'entraînement.

Les distributions sont choisies pour ressembler à la plateforme de démo (faible
trafic de démonstration, quelques erreurs 4xx de saisie, quasi aucune 5xx) ;
elles sont indicatives : en production on ré-entraînerait sur les vraies séries
Prometheus (voir README, section Limites).
"""

from __future__ import annotations

import csv
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from ml.shared.csvio import CSV_COLUMNS, write_csv  # noqa: F401 (ré-export)
from ml.shared.features import FEATURE_NAMES, N_FEATURES

#: Nombre minimal de fenêtres pour entraîner sur des données réelles (quantile 99,9 %
#: et moyennes/écarts-types peu fiables en dessous ; 200 x 15 s = 50 min).
MIN_TRAINING_ROWS = 200

ATTACK_KINDS: tuple[str, ...] = (
    "service_flood",
    "auth_abuse",
    "web_attack",
    "data_corruption",
)


@dataclass(frozen=True)
class Series:
    """Fenêtres réelles chargées d'un CSV, triées par horodatage croissant."""

    data: np.ndarray  # (n, 9) dans l'ordre de FEATURE_NAMES
    ts: tuple[str, ...]  # ISO 8601 UTC
    labels: tuple[str, ...]

    def __len__(self) -> int:
        return len(self.ts)

    def select(self, label: str) -> Series:
        idx = [i for i, lab in enumerate(self.labels) if lab == label]
        return Series(self.data[idx], tuple(self.ts[i] for i in idx),
                      tuple(self.labels[i] for i in idx))


def load_csv(path: Path | str, min_rows: int = MIN_TRAINING_ROWS,
             label: str | None = None) -> Series:
    """Charge et VALIDE un CSV de fenêtres réelles (colonnes : CSV_COLUMNS).

    Les colonnes de features sont lues par nom (l'ordre du fichier est libre) puis
    remises dans l'ordre de FEATURE_NAMES. Lève ValueError si une feature manque,
    si une valeur n'est pas un réel fini >= 0, ou s'il reste moins de `min_rows`
    lignes (après filtrage sur `label` le cas échéant). `label` absent = "normal".
    """
    path = Path(path)
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        header = reader.fieldnames or []
        absent = [c for c in ("ts", *FEATURE_NAMES) if c not in header]
        if absent:
            raise ValueError(f"{path}: colonnes manquantes {absent}")
        rows = []
        for lineno, rec in enumerate(reader, start=2):
            lab = (rec.get("label") or "normal").strip()
            if label is not None and lab != label:
                continue
            try:
                vec = [float(rec[name]) for name in FEATURE_NAMES]
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{path}:{lineno}: valeur non numérique ({exc})") from exc
            if not all(math.isfinite(v) and v >= 0 for v in vec):
                raise ValueError(f"{path}:{lineno}: valeur non finie ou négative {vec}")
            rows.append((rec["ts"], vec, lab))
    if len(rows) < min_rows:
        raise ValueError(
            f"{path}: {len(rows)} fenêtre(s) exploitable(s), minimum {min_rows}"
            + (f" pour le label {label!r}" if label else ""))
    rows.sort(key=lambda r: r[0])  # ISO 8601 UTC : l'ordre lexical est chronologique
    data = np.array([r[1] for r in rows], dtype=float).reshape(len(rows), N_FEATURES)
    return Series(data, tuple(r[0] for r in rows), tuple(r[2] for r in rows))


def generate_baseline(n: int, seed: int = 42) -> np.ndarray:
    """Trafic normal : matrice (n, 9) dans l'ordre de FEATURE_NAMES.

    - req_per_s : Gamma (moyenne ~20 req/s) modulée par un cycle de charge lent.
    - p95_latency_ms : base ~60 ms + dépendance faible à la charge + bruit log-normal.
    - ratio_4xx : Beta (moyenne ~2 %), ratio_5xx : Beta (moyenne ~0,2 %).
    - auth_failed_per_s / waf_blocked_per_s / db_errors_per_s : Poisson lissé (quasi nuls).
    - cpu_pct_max / mem_pct_max : corrélés à la charge, bornés à [0, 100].
    """
    rng = np.random.default_rng(seed)
    load_cycle = 1.0 + 0.25 * np.sin(rng.uniform(0, 2 * np.pi, n))
    req = rng.gamma(shape=16.0, scale=1.25, size=n) * load_cycle
    latency = 60.0 + 0.8 * req + rng.lognormal(mean=2.6, sigma=0.5, size=n)
    r4 = rng.beta(2.0, 98.0, size=n)
    r5 = rng.beta(0.5, 250.0, size=n)
    auth_failed = rng.poisson(0.6, size=n) / 3.0
    waf = rng.poisson(0.4, size=n) / 3.0
    cpu = np.clip(8.0 + 0.55 * req + rng.normal(0, 3.0, size=n), 1.0, 100.0)
    mem = np.clip(32.0 + 0.1 * req + rng.normal(0, 2.5, size=n), 5.0, 100.0)
    db = rng.poisson(0.05, size=n) / 3.0

    data = np.column_stack([req, latency, r4, r5, auth_failed, waf, cpu, mem, db])
    assert data.shape == (n, N_FEATURES)
    return data


def generate_attack(kind: str, n: int, seed: int = 1337) -> np.ndarray:
    """Vecteurs d'attaque simulés du type `kind` (ATTACK_KINDS). Sert à l'évaluation."""
    if kind not in ATTACK_KINDS:
        raise ValueError(f"type d'attaque inconnu: {kind!r} (attendu: {ATTACK_KINDS})")
    rng = np.random.default_rng(seed)
    data = generate_baseline(n, seed=seed + 1)  # point de départ : trafic normal
    col = {name: i for i, name in enumerate(FEATURE_NAMES)}

    if kind == "service_flood":  # saturation : volume, latence, 5xx, CPU
        data[:, col["req_per_s"]] = rng.uniform(150, 600, n)
        data[:, col["p95_latency_ms"]] = rng.uniform(1200, 8000, n)
        data[:, col["ratio_5xx"]] = rng.uniform(0.10, 0.50, n)
        data[:, col["cpu_pct_max"]] = rng.uniform(70, 100, n)
        data[:, col["mem_pct_max"]] = rng.uniform(55, 90, n)
    elif kind == "auth_abuse":  # brute-force / credential stuffing
        data[:, col["auth_failed_per_s"]] = rng.uniform(8, 60, n)
        data[:, col["ratio_4xx"]] = rng.uniform(0.25, 0.70, n)
        data[:, col["req_per_s"]] += rng.uniform(10, 40, n)
    elif kind == "web_attack":  # SQLi / XSS bloqués par le WAF
        data[:, col["waf_blocked_per_s"]] = rng.uniform(4, 40, n)
        data[:, col["ratio_4xx"]] = rng.uniform(0.15, 0.60, n)
        data[:, col["req_per_s"]] += rng.uniform(5, 30, n)
    else:  # data_corruption : erreurs DB, 5xx en cascade, trafic normal
        data[:, col["db_errors_per_s"]] = rng.uniform(1.5, 20, n)
        data[:, col["ratio_5xx"]] = rng.uniform(0.15, 0.80, n)
        data[:, col["p95_latency_ms"]] += rng.uniform(100, 600, n)
    return data
