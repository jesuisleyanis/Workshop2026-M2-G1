# face-id — reconnaissance faciale 1:1 par séquence de poses (consigne additionnelle 1)

Service FastAPI du PC Hôte qui vérifie qu'un **visage correspond à un identifiant** (étape 2 du
back-office durci) et gère l'**enrôlement** des habilitations biométriques.

- **Enrôlement 3 poses** : `face`, `gauche`, `droite` (une photo chacune). La série est refusée en
  bloc avec le détail pose par pose si une photo est inexploitable.
- **Vérification de séquence** : 3 images (une par pose, dans n'importe quel ordre, tirées au sort
  par `auth`) ; chaque image doit montrer la pose demandée **et** le bon visage.
- **RGPD** : gabarits (vecteurs) et vignettes d'enrôlement sont **chiffrés au repos** (AES-256-GCM,
  clé `FACE_DATA_KEY`). Jamais d'image pleine résolution persistée.

Voir le [cahier des charges](CAHIER-DES-CHARGES.md), [l'intégration du modèle](INTEGRATION-ML.md) et
le [cadrage de la consigne](../../docs/consigne-additionnelle-1.md).

## Lancer

```bash
# Dev, backend stub déterministe (aucun modèle requis) :
FACE_INTERNAL_TOKEN=change-me-0123456789 \
FACE_DATA_KEY=$(python -c "import os,base64;print(base64.b64encode(os.urandom(32)).decode())") \
ALLOW_STUB_RECOGNIZER=1 POSTGRES_PASSWORD=dev \
uvicorn face_id.main:create_app --factory --port 8006

# Recette / démo (PC Hôte) : image Docker avec le modèle dlib de l'équipe
docker build -f services/face-id/Dockerfile -t resilience/face-id .   # contexte = racine du dépôt
# (l'image fixe RECOGNIZER_BACKEND=team ; sans Docker : pip install -r requirements.txt -r requirements-team.txt)
```

Configuration (variables d'environnement / secrets SOPS) :

| Variable | Rôle | Défaut |
|---|---|---|
| `FACE_INTERNAL_TOKEN`(`_FILE`) | Token des routes (≥ 16 car.), identique côté `auth` | **requis** |
| `FACE_DATA_KEY`(`_FILE`) | Clé AES-256 des gabarits et photos : base64 de **32 octets** | **requis** |
| `RECOGNIZER_BACKEND` | `team` (dlib) \| `insightface` \| `stub` (dev, exige `ALLOW_STUB_RECOGNIZER=1`) | `stub` (`team` dans l'image) |
| `FACE_MATCH_THRESHOLD` | Distance maximale d'identité (override) | seuil du backend (`team` : 0,6) |
| `POSTGRES_PASSWORD`(`_FILE`) | Accès DB (réseau `data`) | **requis** |
| `RUN_MIGRATIONS` | Applique Alembic au démarrage | `1` |
| `LOG_LEVEL` | Niveau de log | `INFO` |

> **Perdre `FACE_DATA_KEY` rend tous les enrôlements illisibles** (réenrôlement requis) ; la changer
> a le même effet. Elle vit dans SOPS, jamais dans le dépôt ni dans les logs.

## API (toutes les routes `/api/v1/*` exigent `X-Internal-Token`)

| Méthode & chemin | Corps / réponse |
|---|---|
| `POST /api/v1/enroll` | `{username, enrolled_by, poses:{face,gauche,droite:<b64>}}` → `200 {enrolled:true, model_version, poses:[…]}` · `422 enrollment_rejected` (+ `details:[{pose, reason}]`, `reason` ∈ `no_face`, `multiple_faces`, `wrong_pose`, `inconsistent`, `invalid_image`, `missing`) · `404 unknown_user` |
| `POST /api/v1/verify` | `{username, frames:[{pose, image_b64}×3]}` (3 poses distinctes) → `200 {match, model_version}`. Le motif d'un échec n'est **que dans les logs** (`face_verify_nomatch` / `face_verify_error`). Identifiant inconnu ⇒ `match:false` (anti-énumération). |
| `DELETE /api/v1/enroll/{username}` | `204` · `404 not_enrolled` |
| `GET /api/v1/enrollments` | `[{username, enrolled_at, enrolled_by, model_version, poses}]` — **aucune biométrie** |
| `GET /api/v1/enrollments/{username}/photos?viewer=<admin>` | `200 {photos:{face,gauche,droite:<b64 JPEG ≤ 240 px>}}` · `404` ; chaque consultation est journalisée (`face_photos_viewed`, qui regarde qui) |
| `GET /health` · `/ready` · `/metrics` | sondes et métriques Prometheus |

Erreurs au format du contrat : `{"error":{"code","message"}}` (+ `details` pour `enrollment_rejected`).
Codes : `internal_token_invalid` (401), `validation_error` / `invalid_image` (422), `unknown_user`,
`not_enrolled`, `photos_unavailable` (404), `internal_error` (500).

Les lignes **v1** (gabarit float32 non chiffré, sans photos) ou enrôlées avec un autre modèle ne
plantent rien : `verify` répond `match:false` + log `face_verify_error` (**réenrôlement requis**),
`photos` répond `404`.

## Tester

```bash
cd services/face-id && python -m pytest -q -p no:cacheprovider
```

Les tests sont **déterministes** grâce au `StubRecognizer` : une image de test est `b"<pose>|<identité>"`
(`b"face|alice"`), `b"none"` = aucun visage, `b"many"` = plusieurs visages. **Aucun modèle ni matériel**
n'est requis. La qualité de reconnaissance réelle et le seuil se valident **en recette** (backend `team`).

## Recette : enrôler puis vérifier

```bash
H="X-Internal-Token: $FACE_INTERNAL_TOKEN"
# 1) Enrôler op01 (3 photos JPEG : face, tête tournée à gauche, tête tournée à droite)
curl -s -X POST localhost:8006/api/v1/enroll -H "$H" -H 'Content-Type: application/json' -d "{
  \"username\":\"op01\",\"enrolled_by\":\"admin01\",
  \"poses\":{\"face\":\"$(base64 -w0 face.jpg)\",\"gauche\":\"$(base64 -w0 gauche.jpg)\",\"droite\":\"$(base64 -w0 droite.jpg)\"}}"
# -> {"enrolled":true,"model_version":"team-dlib-face_recognition-1.3.0","poses":["face","gauche","droite"]}

# 2) Vérifier (ordre libre) : 3 images de la même personne
curl -s -X POST localhost:8006/api/v1/verify -H "$H" -H 'Content-Type: application/json' -d "{
  \"username\":\"op01\",\"frames\":[
   {\"pose\":\"droite\",\"image_b64\":\"$(base64 -w0 v_droite.jpg)\"},
   {\"pose\":\"face\",\"image_b64\":\"$(base64 -w0 v_face.jpg)\"},
   {\"pose\":\"gauche\",\"image_b64\":\"$(base64 -w0 v_gauche.jpg)\"}]}"
# -> {"match":true,"model_version":"team-dlib-face_recognition-1.3.0"}
```

Seuils de pose (rotation du nez dans la mâchoire) : `|rot| ≤ 0,10` face, `rot ≥ 0,15` gauche,
`rot ≤ −0,15` droite ; zone morte entre les deux ⇒ `wrong_pose`. Identité : distance euclidienne ≤ 0,6.

## Place dans le flux

`back-office` → `auth` `/auth/face` → **`face-id /verify`** → `match` ⇒ `auth` débloque la saisie
du mot de passe. `face-id` ne délivre **aucun jeton** : la décision d'accès reste dans `auth`.
