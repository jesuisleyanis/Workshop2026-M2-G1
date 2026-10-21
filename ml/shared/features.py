"""Vecteur de features ML — SOURCE DE VÉRITÉ (docs/contracts.md §2).

Le collector, le training et le detector importent TOUS cette définition.
Jamais de duplication : l'ordre et la liste ci-dessous sont figés.

    [ req_per_s, p95_latency_ms, ratio_4xx, ratio_5xx,
      auth_failed_per_s, waf_blocked_per_s,
      cpu_pct_max, mem_pct_max, db_errors_per_s ]

Ce module contient aussi :
  * des utilitaires statistiques (z-score avec plancher d'écart-type, top features) ;
  * `classify_incident` : HEURISTIQUE DE ROUTAGE par règles.

IMPORTANT (exigence R8) — `classify_incident` n'est PAS la détection.
La décision « anomalie / pas anomalie » est prise par le modèle IsolationForest
(ml/training, ml/detector). Une fois l'anomalie décidée par le modèle, cette
fonction se contente d'étiqueter le type d'incident pour que la remédiation
sache quelle ligne de la table de décision (contracts.md §4) appliquer. C'est une
limite assumée (contracts.md §3, sujet §3.3) : le modèle dit « ça n'est pas normal »,
pas « c'est un flood ».
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence

from resilience_common import IncidentType

# --- Définition figée du vecteur ------------------------------------------------

FEATURE_NAMES: tuple[str, ...] = (
    "req_per_s",
    "p95_latency_ms",
    "ratio_4xx",
    "ratio_5xx",
    "auth_failed_per_s",
    "waf_blocked_per_s",
    "cpu_pct_max",
    "mem_pct_max",
    "db_errors_per_s",
)
N_FEATURES: int = len(FEATURE_NAMES)
FEATURE_INDEX: dict[str, int] = {name: i for i, name in enumerate(FEATURE_NAMES)}

#: Fenêtre d'agrégation du vecteur côté contrat (secondes) = PROM_RATE_WINDOW du collector ;
#: un vecteur par seconde (COLLECT_INTERVAL_SECONDS). Détection < 5 s : docs/plan-amelioration-detection.md.
WINDOW_SECONDS: int = 5

# Plancher de l'écart-type utilisé pour le z-score. Sans lui, une feature quasi
# constante en baseline (ex. db_errors_per_s ~ 0) produirait des z astronomiques
# pour un écart insignifiant. Valeurs = « plus petit écart qui a un sens métier ».
STD_FLOOR: dict[str, float] = {
    "req_per_s": 1.0,
    "p95_latency_ms": 20.0,
    "ratio_4xx": 0.01,
    "ratio_5xx": 0.005,
    "auth_failed_per_s": 0.2,
    "waf_blocked_per_s": 0.2,
    "cpu_pct_max": 2.0,
    "mem_pct_max": 2.0,
    "db_errors_per_s": 0.05,
}

# --- Conversions ----------------------------------------------------------------


def vector_from_dict(values: Mapping[str, float]) -> list[float]:
    """Construit le vecteur ordonné depuis un dict ; lève KeyError si une feature manque."""
    return [float(values[name]) for name in FEATURE_NAMES]


def vector_to_dict(vector: Sequence[float]) -> dict[str, float]:
    """Inverse de `vector_from_dict` ; valide la longueur."""
    validate_vector(vector)
    return {name: float(v) for name, v in zip(FEATURE_NAMES, vector)}


def validate_vector(vector: Sequence[float]) -> None:
    """Lève ValueError si la longueur est incorrecte ou si une valeur n'est pas finie."""
    if len(vector) != N_FEATURES:
        raise ValueError(f"vecteur de {len(vector)} features, {N_FEATURES} attendues")
    for name, v in zip(FEATURE_NAMES, vector):
        if not math.isfinite(v):
            raise ValueError(f"feature {name} non finie: {v!r}")


# --- Statistiques ---------------------------------------------------------------


def zscores(
    vector: Sequence[float],
    means: Mapping[str, float],
    stds: Mapping[str, float],
) -> dict[str, float]:
    """Z-score signé de chaque feature vs la baseline (écart-type planché par STD_FLOOR)."""
    validate_vector(vector)
    out: dict[str, float] = {}
    for name, v in zip(FEATURE_NAMES, vector):
        std = max(float(stds[name]), STD_FLOOR[name])
        out[name] = (float(v) - float(means[name])) / std
    return out


def top_features(
    vector: Sequence[float],
    z: Mapping[str, float],
    k: int = 3,
    min_abs_z: float = 2.0,
) -> list[dict[str, float | str]]:
    """Les k features les plus écartées de la baseline (|z| décroissant).

    Ne garde que celles dont |z| >= min_abs_z ; si aucune n'atteint ce seuil
    (anomalie purement multivariée détectée par le modèle), renvoie quand même la
    plus déviante pour que l'événement ne soit jamais vide.
    """
    values = vector_to_dict(vector)
    ranked = sorted(FEATURE_NAMES, key=lambda n: abs(z[n]), reverse=True)
    kept = [n for n in ranked if abs(z[n]) >= min_abs_z][:k] or ranked[:1]
    return [{"name": n, "value": values[n], "z": round(z[n], 3)} for n in kept]


# --- Heuristique de routage -----------------------------------------------------

#: z minimal pour qu'un signal soit considéré « présent » dans le routage.
SIGNAL_Z_MIN: float = 3.0


def classify_incident(z: Mapping[str, float]) -> IncidentType:
    """Étiquette le type d'incident à partir des z-scores des features. HEURISTIQUE.

    Rôle : router un événement DÉJÀ jugé anormal par le modèle ML vers la bonne
    ligne de la table de décision. Ce n'est pas un détecteur : appelée sur un
    vecteur normal elle renvoie `unknown`, et elle n'est jamais utilisée pour
    décider s'il y a anomalie.

    Règles (le groupe de signaux au z le plus élevé gagne, s'il dépasse SIGNAL_Z_MIN) :
      * data_corruption : db_errors_per_s ↑
      * auth_abuse      : auth_failed_per_s ↑
      * web_attack      : waf_blocked_per_s ↑
      * service_flood   : req_per_s ↑, ou (p95_latency_ms ↑ ET ratio_5xx ↑ sans
                          erreurs DB dominantes — sinon c'est de la corruption,
                          pas un problème de disponibilité)
      * unknown         : aucun groupe n'atteint le seuil (anomalie sans signature claire)

    Limite assumée : un attaquant qui combine plusieurs vecteurs est étiqueté par
    le signal le plus fort ; en cas de doute la remédiation retombe sur `unknown`
    (dry-run + escalade, aucune action destructive).
    """
    # Seul le dépassement vers le HAUT est un signal d'attaque.
    pos = {n: max(z.get(n, 0.0), 0.0) for n in FEATURE_NAMES}

    flood = pos["req_per_s"]
    if pos["db_errors_per_s"] < SIGNAL_Z_MIN:
        flood = max(flood, min(pos["p95_latency_ms"], pos["ratio_5xx"]))

    scores: dict[IncidentType, float] = {
        IncidentType.DATA_CORRUPTION: pos["db_errors_per_s"],
        IncidentType.AUTH_ABUSE: pos["auth_failed_per_s"],
        IncidentType.WEB_ATTACK: pos["waf_blocked_per_s"],
        IncidentType.SERVICE_FLOOD: flood,
    }
    best, best_z = max(scores.items(), key=lambda kv: kv[1])
    return best if best_z >= SIGNAL_Z_MIN else IncidentType.UNKNOWN
