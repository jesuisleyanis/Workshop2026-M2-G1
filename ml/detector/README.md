# ml/detector

Service FastAPI (port interne **8003**, réseau `app`). Relève `collector`, score avec l'IsolationForest, notifie la remédiation.

## Configuration

| Variable | Défaut | Rôle |
|---|---|---|
| `MODEL_DIR` | `/app/artifacts` | `model.joblib` + `baseline_stats.json` (produits par `ml/training`) |
| `COLLECTOR_URL` | `http://collector:8004` | source des features |
| `REMEDIATION_URL` | `http://remediation:8005/events` | destination des `AnomalyEvent` — URL **complète** de l'endpoint, POSTée telle quelle (testé : `tests/test_compose_wiring.py`) |
| `REMEDIATION_TOKEN` / `REMEDIATION_TOKEN_FILE` | — | token Bearer (le fichier, ex. secret SOPS, est prioritaire) |
| `TARGET_SERVICE` | `payment-api` | label `service` de la métrique et de l'événement |
| `FEATURES_WAIT_SECONDS` | `5` | attente longue sur le collector (`?after=<seq>`) : chaque collecte est scorée dès qu'elle existe ; `0` = relève périodique |
| `POLL_INTERVAL_SECONDS` | `1` | pause après une relève en échec (ou période si attente longue désactivée) |
| `EVENT_COOLDOWN_SECONDS` | `60` | un seul événement par fenêtre pendant qu'une anomalie persiste |
| `ANOMALY_THRESHOLD` | seuil de `baseline_stats.json` | surcharge optionnelle |
| `ANOMALY_CONFIRM_WINDOWS` | calibration (`confirm_windows`, 1 si non calibré) | fenêtres consécutives au-dessus du seuil pour confirmer ; une seule suffit au-dessus de `threshold_high` |
| `LOKI_URL` | `http://loki:3100` | IP source dominante des logs WAF (`source_ip` de l'événement) ; vide = désactivé |
| `SOURCE_IP_WINDOW_SECONDS` / `SOURCE_IP_MIN_SHARE` | `30` / `0.6` | fenêtre et part minimale des lignes WAF pour retenir une IP |

## Décision : qui décide quoi

1. **Décideur = le modèle.** `anomaly_score = -IsolationForest.score_samples(x)` ∈ (0,1] ; anomalie si `score >= threshold` (0,6296).
2. **Garde-fou statistique (filet, pas décideur).** Si le score reste sous le seuil mais qu'une feature dépasse `guardrail_z` écarts-types
   (>= 15, calibré hors de la plage normale de la baseline), on escalade (`trigger="guardrail"`). Il existe parce qu'une IsolationForest
   dilue un pic extrême porté par une seule feature (cf. `training/README.md`, Limites). Tracé dans les logs et `/api/v1/status`.
3. **Routage.** `incident_type` = `ml.shared.features.classify_incident(z)` — heuristique de routage vers la table de décision.

## Événement émis (contrat §3)

Construit et validé avec `resilience_common.AnomalyEvent` : `features_top` = les 3 features les plus déviantes avec leur z-score ;
`evidence` = requêtes Prometheus + Loki propres au type d'incident. Log JSON `anomaly_detected` (avec `anomaly_score`).

## API

`GET /health` · `GET /ready` (503 si modèle absent/altéré, token absent ou collector sans données) · `GET /metrics`
(`resilience_anomaly_score{service}`) · `GET /api/v1/status` (dernier score, déclencheur, version du modèle).

## Lancer / tester

```bash
python -m ml.training.train                                     # 1) produire les artefacts
MODEL_DIR=ml/training/artifacts REMEDIATION_TOKEN=... \
  uvicorn ml.detector.app:create_app --factory --port 8003      # 2) depuis la racine du dépôt
cd ml && python -m pytest detector                              # tests (POST remédiation mocké)
docker build -f ml/detector/Dockerfile -t resilience/detector . # image : le modèle est entraîné AU BUILD
```

## Modèle : entraîné au build (reproductibilité)

Le modèle n'est **pas commité** (`ml/training/artifacts/` est dans `.gitignore`). L'image n'attend
aucun artefact pré-calculé : son étape `trainer` lance `ml.training.train` sur
`ml/training/data/baseline_real.csv` (+ `calibration.json`) s'ils sont versionnés, sinon sur la baseline
synthétique (cf. `ml/training/README.md` §6). Le scikit-learn d'entraînement est donc toujours celui du runtime.
Si `calibration.json` a été calculée sur un autre modèle, l'entraînement échoue (code 3) et **le build aussi** :
l'image ne part jamais avec un seuil qui ne correspond pas à son modèle. L'étape `ml-tools` du même Dockerfile
sert aux cibles `make train` / `calibrate` / `test-ml` (dev uniquement, hors image finale).

- **Versions épinglées** : `scikit-learn==1.9.1`, `numpy`, `joblib` sont figés **à l'identique** côté
  entraînement (`ml/training/requirements.txt`) et detector (`ml/detector/requirements.txt`). Une dérive fausserait silencieusement les scores.
- **Vérifications au chargement** (`ml/detector/model.py`) : `feature_names` == `ml.shared.features`,
  `sha256(model.joblib)` == `baseline_stats.json.model_sha256` (refus sinon), et **avertissement
  journalisé** si la version scikit-learn installée diffère de `sklearn_version` enregistrée à l'entraînement.
