# ml/training

Entraîne l'IsolationForest qui décide des anomalies (exigence R8 ; documentation §3.3 du sujet).

```bash
python -m ml.training.train [--n-samples 20000] [--seed 42] [--version 1.0.0] [--n-estimators 200] [--out DIR]
```

Sortie (défaut `ml/training/artifacts/`) : `v<version>/{model.joblib,baseline_stats.json}` + copie « courante » à la racine
(celle lue par le detector via `MODEL_DIR`). Tests : `cd ml && python -m pytest training`.

## 1. Données

Aucune donnée réelle n'existe avant le déploiement : `dataset.py` **simule** du trafic normal de la plateforme de démo
(20 000 fenêtres de 15 s, seed 42) : `req_per_s` ~ Gamma (moyenne 20) modulé par un cycle de charge ; latence p95 ~ 60 ms +
dépendance à la charge + bruit log-normal ; `ratio_4xx` ~ Beta (≈ 2 %) ; `ratio_5xx` ~ Beta (≈ 0,2 %) ; échecs d'auth, blocages WAF et
erreurs DB ~ Poisson quasi nuls ; CPU/RAM corrélés à la charge. Les attaques simulées (`generate_attack`) reprennent la
signature de chaque scénario (flood, brute-force auth, attaque web, corruption DB) et ne servent **qu'à évaluer**.

## 2. Préparation

Vecteur de 9 features dans l'ordre de `ml.shared.features`. Aucune normalisation : les arbres d'isolation sont invariants à
l'échelle. On calcule moyenne/écart-type par feature (`baseline_stats.json`) pour les z-scores.

## 3. Modèle

`IsolationForest(n_estimators=200, max_samples=1024, contamination="auto", random_state=seed)`. Score d'anomalie =
`-score_samples` ∈ (0, 1] (≈ 0,42 en moyenne sur du normal, > 0,65 sur les attaques). **Seuil** = `max(0.60, quantile 99,9 % des
scores de la baseline)` = **0,6296**. `max_samples=1024` (au lieu de 256) a nettement amélioré la séparation des attaques mono-signal
(détection auth_abuse 38 % -> 99 %).

**Garde-fou statistique** (`guardrail_z` = `max(15, 1,5 × z max de la baseline)` = 15) : filet de sécurité documenté, pas le décideur (voir Limites).

## 4. Résultats (jeu normal held-out + attaques simulées, n = 2000 chacun, seed 42)

| Jeu | Détection par le **modèle seul** | Avec garde-fou | Routage `incident_type` correct |
|---|---|---|---|
| normal (faux positifs) | 0,0 % | 0,0 % | — |
| service_flood | 100 % | 100 % | 100 % |
| auth_abuse | 98,6 % | 100 % | 100 % |
| web_attack | 95,7 % | 100 % | 100 % |
| data_corruption | 100 % | 100 % | 100 % |

Les chiffres complets sont écrits dans `baseline_stats.json` (`evaluation`) à chaque entraînement.

## 5. Limites (assumées)

- **Données simulées.** Les résultats ci-dessus mesurent la séparation entre *notre* simulation du normal et *notre* simulation des attaques :
  ils sont optimistes (routage 100 % = circulaire, les attaques simulées sont franches). La vraie validation, c'est le rejeu `make attack` sur la stack ;
  il faudra ré-entraîner sur les vraies séries Prometheus d'une période calme (`--n-samples` + dataset réel) avant le jury.
- **Pic mono-feature.** Une IsolationForest dilue le score d'une anomalie portée par une seule feature sur 9 : un `req_per_s` à 600 avec le reste
  normal score ≈ 0,48 (< seuil). C'est ce cas que couvre le garde-fou |z| >= 15 (testé). Les attaques réelles touchent en général plusieurs features.
- **Non supervisé.** Le modèle dit « anormal », pas « quel type » : le type vient de l'heuristique de routage (`ml/shared`).
- **Stationnarité.** Une montée de charge légitime (pic de trafic normal) peut être jugée anormale ; pas de saisonnalité modélisée.
- **Sérialisation.** `joblib` = pickle, version scikit-learn à garder identique entre training et detector (épinglée dans `requirements.txt`).
