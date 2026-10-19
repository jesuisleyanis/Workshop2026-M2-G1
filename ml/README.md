# ml/ — détection d'anomalies (AIOps) · exigence R8

```
Prometheus ──PromQL──► collector ──GET /api/v1/features──► detector ──POST /events──► remediation
 (cAdvisor, services)   (8004)        vecteur 9 features     (8003)    AnomalyEvent      (8005)
                                                          IsolationForest   (Bearer token)
                         ml/shared/features.py  ◄── source de vérité du vecteur (training + collector + detector)
                         ml/training            ──► model.joblib + baseline_stats.json
```

| Dossier | Rôle | Doc |
|---|---|---|
| `shared/` | définition figée du vecteur de features, z-scores, heuristique de routage `incident_type` | [README](shared/README.md) · [CDC](shared/CAHIER-DES-CHARGES.md) |
| `collector/` | interroge Prometheus toutes les 15 s, expose le vecteur | [README](collector/README.md) · [CDC](collector/CAHIER-DES-CHARGES.md) |
| `training/` | dataset baseline simulé, entraînement IsolationForest, artefacts versionnés | [README](training/README.md) · [CDC](training/CAHIER-DES-CHARGES.md) |
| `detector/` | score temps réel, métrique, AnomalyEvent vers la remédiation | [README](detector/README.md) · [CDC](detector/CAHIER-DES-CHARGES.md) |

**Qui décide quoi (R8).** Le *décideur* est le modèle (IsolationForest). Les seuils statistiques (z-score) ne sont qu'un
garde-fou documenté ; la classification `incident_type` n'est qu'une heuristique de **routage** vers la table de décision.

## Lancer les tests (local, pas de CI)

```bash
python3 -m venv /tmp/rc-ml && /tmp/rc-ml/bin/pip install -r ml/requirements-dev.txt
cd ml && /tmp/rc-ml/bin/python -m pytest           # 50 tests, ~2 s
```

## Entraîner puis construire les images (contexte = racine du dépôt)

```bash
/tmp/rc-ml/bin/python -m ml.training.train                       # écrit ml/training/artifacts/
docker build -f ml/detector/Dockerfile  -t resilience/detector  .
docker build -f ml/collector/Dockerfile -t resilience/collector .
```

Ports internes : collector `8004`, detector `8003` (réseau `app`, jamais publiés sur l'hôte).
