# Cahier des charges — ml/training

**Pourquoi.** R8 : la détection doit venir d'un **modèle ML**, pas de `if` codés en dur. Ce composant produit ce modèle de façon
reproductible, ainsi que les statistiques de baseline nécessaires à l'explicabilité (z-scores) et au garde-fou.

**Périmètre.**
- Génération programmatique d'un dataset de trafic **normal** (`dataset.py`) et d'attaques simulées (évaluation seulement).
- Entraînement d'un `IsolationForest` scikit-learn (non supervisé : il n'apprend que le normal).
- Artefacts versionnés : `model.joblib` (+ métadonnées, version, version sklearn) et `baseline_stats.json`
  (moyennes, écarts-types, planchers, **seuil**, garde-fou, hash sha256 du modèle, évaluation).
- CLI reproductible : `python -m ml.training.train --seed 42 --n-samples 20000 --version 1.0.0`.
- Documentation données / préparation / modèle / résultats / limites exigée par le sujet §3.3 -> README.

**Critères d'acceptation.** Le modèle s'entraîne ; sépare un vecteur normal d'un vecteur d'attaque ; faux positifs <= 1 % sur du
normal held-out ; détection >= 90 % par type d'attaque simulée ; deux exécutions à seed égal donnent les mêmes statistiques.

**Sécurité.** `joblib` est un pickle : le detector ne charge `model.joblib` que si son sha256 correspond à `baseline_stats.json`.
Aucun secret ni donnée réelle ; données 100 % fictives.
