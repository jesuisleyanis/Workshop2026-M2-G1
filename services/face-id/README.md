# face-id — reconnaissance faciale 1:1 (consigne additionnelle 1)

Service FastAPI du PC Hôte qui vérifie qu'un **visage correspond à un identifiant** (étape 2 du
back-office durci) et gère l'**enrôlement** des habilitations biométriques. **RGPD : seul
l'embedding est stocké, jamais l'image.** Voir le [cahier des charges](CAHIER-DES-CHARGES.md) et
le [cadrage de la consigne](../../docs/consigne-additionnelle-1.md).

## Lancer

```bash
# Backend par défaut (stub déterministe, aucun modèle requis) :
FACE_INTERNAL_TOKEN=change-me-0123456789 \
POSTGRES_PASSWORD=dev \
uvicorn face_id.main:create_app --factory --port 8006

# Backend réel (recette, PC Hôte) : installer les deps commentées de requirements.txt puis
RECOGNIZER_BACKEND=insightface FACE_MATCH_THRESHOLD=0.35 ...
```

Configuration (variables d'environnement / secrets SOPS) :

| Variable | Rôle | Défaut |
|---|---|---|
| `FACE_INTERNAL_TOKEN`(`_FILE`) | Token des routes d'enrôlement (≥ 16 car.) | **requis** |
| `RECOGNIZER_BACKEND` | `stub` \| `insightface` | `stub` |
| `FACE_MATCH_THRESHOLD` | Seuil de similarité cosinus (override) | seuil du backend |
| `POSTGRES_PASSWORD`(`_FILE`) | Accès DB (réseau `data`) | **requis** |
| `RUN_MIGRATIONS` | Applique Alembic au démarrage | `1` |
| `LOG_LEVEL` | Niveau de log | `INFO` |

## Tester

```bash
# Depuis la racine du dépôt, dans le venv du projet :
PYTHONPATH=services/face-id/src python -m pytest services/face-id/tests -q
```

Les tests sont **déterministes** grâce au `StubRecognizer` (image identique ⇒ correspondance,
image différente ⇒ non-correspondance) : **aucun modèle ni matériel** n'est requis. La qualité de
reconnaissance réelle et le seuil se valident **en recette** sur le PC Hôte (backend `insightface`).

## Appels

```bash
# Enrôler (admin) :
curl -X POST localhost:8006/api/v1/enroll -H "X-Internal-Token: $FACE_INTERNAL_TOKEN" \
  -d '{"username":"op01","images_b64":["<jpeg-b64>"],"enrolled_by":"admin01"}'

# Vérifier (appelé par auth) :
curl -X POST localhost:8006/api/v1/verify \
  -d '{"username":"op01","image_b64":"<jpeg-b64>"}'
# -> {"match":true,"score":0.72,"threshold":0.35,"model_version":"insightface-buffalo_s-1.0"}
```

## Place dans le flux

`back-office` → `auth` `/auth/face` → **`face-id /verify`** → `match` ⇒ `auth` débloque la saisie
du mot de passe. `face-id` ne délivre **aucun jeton** : la décision d'accès reste dans `auth`.
