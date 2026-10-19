# ml/training

Entraîne l'IsolationForest qui décide des anomalies (exigence R8 ; documentation §3.3 du sujet).

```bash
python -m ml.training.train [--n-samples 20000] [--seed 42] [--version 1.0.0] [--n-estimators 200] [--out DIR] \
    [--data baseline_real.csv] [--attack-data attacks_real.csv] [--calibration calibration.json]
python -m ml.training.calibrate [--normal ...] [--attacks ...] [--model-dir ...] [--margin 0.5] [--max-mttd 20] [--out ...]
```

Sortie (défaut `ml/training/artifacts/`) : `v<version>/{model.joblib,baseline_stats.json}` + copie « courante » à la racine
(celle lue par le detector via `MODEL_DIR`). Tests : `cd ml && python -m pytest training`.

**L'image du detector entraîne le modèle à son build** (`ml/detector/Dockerfile`, étape `trainer`) : sur
`data/baseline_real.csv` + `data/calibration.json` s'ils sont présents, sinon sur la baseline synthétique. Pour passer en
production le modèle réel, il suffit donc de versionner ces deux fichiers puis `docker compose build detector` (§6).

## 1. Données

**Cible (avant le jury) : vraies séries Prometheus** — voir §6. `load_csv` lit le CSV capturé (`ml.shared.csvio`) et le valide :
les 9 colonnes de features présentes (ordre libre), valeurs réelles finies >= 0, au moins 200 fenêtres normales (50 min à 15 s).
Le held-out est **chronologique** : les 20 % de fenêtres les plus récentes (deux fenêtres voisines sont autocorrélées ; un tirage
aléatoire mettrait des quasi-doublons des deux côtés et surestimerait la qualité).

**Repli : données simulées.** Sans capture, `dataset.py` **simule** du trafic normal de la plateforme de démo
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
  ils sont optimistes (routage 100 % = circulaire, les attaques simulées sont franches). La vraie validation, c'est le rejeu `make attack` sur la stack :
  c'est ce que fait la procédure du §6 (capture réelle, `attacks_real` dans l'évaluation, calibration). Tant qu'elle n'a pas été jouée, le modèle
  embarqué est le synthétique.
- **Le normal de la démo doit être celui de la capture.** Le modèle juge anormal ce qu'il n'a pas vu : la baseline est capturée avec
  `scripts/gen_normal_traffic.py`, qu'il faut aussi rejouer en démo (temps 1 et fond pendant l'attaque), au même débit.
- **Pic mono-feature.** Une IsolationForest dilue le score d'une anomalie portée par une seule feature sur 9 : un `req_per_s` à 600 avec le reste
  normal score ≈ 0,48 (< seuil). C'est ce cas que couvre le garde-fou |z| >= 15 (testé). Les attaques réelles touchent en général plusieurs features.
- **Non supervisé.** Le modèle dit « anormal », pas « quel type » : le type vient de l'heuristique de routage (`ml/shared`).
- **Stationnarité.** Une montée de charge légitime (pic de trafic normal) peut être jugée anormale ; pas de saisonnalité modélisée.
- **Sérialisation.** `joblib` = pickle, version scikit-learn à garder identique entre training et detector (épinglée dans `requirements.txt`).

## 6. Ré-entraîner sur les vraies séries Prometheus (procédure avant le jury)

Prérequis : Docker, `make` (Windows : `winget install ezwinports.make`, à lancer depuis Git Bash), `make up-full`
(Prometheus + cAdvisor), `make seed`. **Aucun Python ML à installer sur le poste** : `train`, `calibrate` et `test-ml`
tournent dans l'image `ml-tools` (étape du Dockerfile detector), qui a le même Python 3.12 et le même scikit-learn que le
build du detector. C'est ce qui garantit que le modèle calibré est **exactement** celui que l'image ré-entraîne.

Toutes les captures tournent **dans le conteneur collector**
(seul à joindre Prometheus, réseau `obs`) avec **sa** fenêtre `PROM_RATE_WINDOW` et **son** pas `COLLECT_INTERVAL_SECONDS` :
les fenêtres capturées ont exactement la définition de celles que le detector score en démo. Si ces deux variables changent,
il faut tout recapturer.

| # | Commande | Effet |
|---|---|---|
| 1 | `make capture-baseline` (`DURATION=60m` par défaut) | joue 60 min de trafic légitime (`scripts/gen_normal_traffic.py`), capture dans un `.tmp` et ne remplace `data/baseline_real.csv` que s'il contient au moins 200 fenêtres (50 min à 15 s) |
| 2 | `make train` (facultatif) | aperçu : modèle sur la baseline réelle (held-out chronologique), faux positifs |
| 3 | `make capture-attack SC=service_flood` (puis `auth_abuse`, `web_attack`, `data_corruption`) | joue le scénario (`ATTACK_S=20` s) sur fond de trafic normal ; étiquette **seulement** la fenêtre attaque + 30 s (retombée des `rate()`) et l'ajoute à `data/attacks_real.csv` via un `.tmp` |
| 4 | `make calibrate` | ré-entraîne **sans** calibration puis place le seuil entre le normal et le pic le plus faible des attaques ; MTTD par scénario ; écrit `data/calibration.json` (+ `calibration.report.json`, toujours) |
| 5 | `make train` | ré-entraîne avec la calibration (même empreinte, sinon échec) ; rapport `attaques RÉELLES` (détection, score max, routage) |
| 6 | `git add ml/training/data/*.csv ml/training/data/calibration.json` puis `docker compose -f infra/compose/docker-compose.yml build detector` | l'image du detector embarque le modèle réel |

Lecture des résultats de `calibrate` (code retour) :
- **0** : séparable et MTTD <= `--max-mttd` (20 s) pour chaque passage de chaque scénario.
- **1 — non séparable** : un scénario ne dépasse jamais le normal. `calibration.json` n'est pas écrit, mais `data/calibration.report.json` l'est toujours et marque `"separable": false` sur le(s) scénario(s) en cause. Leviers : capturer un normal plus long/varié
  (débits différents via `--rps`), vérifier que le scénario produit bien ses métriques (`missing` dans le CSV), `--n-estimators`.
  Jamais un `if` codé en dur (R8).
- **2 — MTTD trop long** : seuil écrit, mais un scénario met trop de fenêtres à franchir le seuil. Leviers : `--margin` plus bas
  (seuil plus près du normal, au prix de faux positifs), raccourcir `PROM_RATE_WINDOW`/`COLLECT_INTERVAL_SECONDS` (puis recapturer).

Le MTTD de `calibrate` est celui du **modèle** (résolution = un pas de capture). En démo s'y ajoutent le scrape Prometheus,
la relève du detector (`POLL_INTERVAL_SECONDS`) et la remédiation : c'est le MTTD affiché par le dashboard qui fait foi.

**Garde-fou d'empreinte.** `model_fingerprint` (scores du modèle sur un jeu sonde fixe) est écrit dans
`baseline_stats.json` et `calibration.json`. Si `train --calibration` produit un modèle différent de celui qui a été calibré
(baseline recapturée, seed ou scikit-learn changés), il **échoue** (code 3, rien n'est écrit) : appliquer un seuil calculé pour
un autre modèle donnerait un detector mal réglé sans aucun signe visible. Le build du detector échoue donc aussi, au lieu
d'embarquer ce seuil. Remède : `make calibrate`. `--allow-stale-calibration` force l'entraînement en **ignorant** la
calibration (retour au seuil par quantile, tracé dans `calibration_ignored`), jamais en gardant le seuil périmé.

Tests en Python 3.12 sans rien installer : `make test-ml`.
