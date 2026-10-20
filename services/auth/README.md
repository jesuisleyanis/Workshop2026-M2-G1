# services/auth

Service d'authentification FastAPI (JWT HS256, bcrypt, rate-limit slowapi) de la plateforme fictive RESILIENCE-ALPHA. Cadrage, exigences et critères d'acceptation : [`CAHIER-DES-CHARGES.md`](CAHIER-DES-CHARGES.md). Contrats transverses : [`docs/contracts.md`](../../docs/contracts.md).

- **Port interne** `8002` — **réseau** `app` (+ `data` pour PostgreSQL) — **nom Compose** `auth`

## Architecture interne

```
requête ─► RequestContextMiddleware ─► route FastAPI ─► SQLAlchemy ─► PostgreSQL (resilience_db)
              (request_id, client_ip)      │  ▲
                                           │  └─ slowapi (rate-limit /login, limite dynamique)
                                           ├─► FaceIdClient ─► face-id (vérification + habilitations)
                                           ├─► MqttLedNotifier ─► Mosquitto ─► LED ESP8266
                                           ├─► logs JSON (resilience_common.logging.get_logger)
                                           └─► métriques (resilience_common.metrics)
```

```
services/auth/
├── CAHIER-DES-CHARGES.md
├── README.md
├── Dockerfile                 # multi-étapes, slim, non-root, HEALTHCHECK /health
├── Dockerfile.dockerignore    # contexte de build minimal
├── requirements.txt           # dépendances runtime épinglées (source unique, lue par pyproject)
├── requirements-dev.txt       # + pytest, httpx, ruff
├── pyproject.toml
├── src/auth_service/
│   ├── main.py                # create_app() : routes, handlers d'erreurs, lifespan (migrations)
│   ├── config.py              # Settings.from_env() — refuse les secrets faibles/absents
│   ├── security.py            # création/décodage du JWT, comparaison du token interne
│   ├── backoffice.py          # auth à étapes identifiant → visage → mot de passe (+ GET /auth/device)
│   ├── challenge.py           # challenges (poses aléatoires), verrouillage, refroidissements
│   ├── face_client.py         # FaceIdClient : verify / enroll / revoke / enrollments / photos
│   ├── led_mqtt.py            # MqttLedNotifier : états LED vers Mosquitto (fail-open)
│   ├── admin.py               # API d'administration des habilitations + bootstrap
│   ├── ratelimit.py           # DynamicRateLimit : limite courante, tighten(), reset()
│   ├── schemas.py             # modèles Pydantic d'entrée/sortie
│   └── observability.py       # contexte de requête, filtre de logs, format d'erreur contrat
└── tests/                     # pytest, SQLite en mémoire
```

Le schéma DB, le hash bcrypt et le seed viennent de [`libs/python/resilience_db`](../../libs/python/resilience_db/README.md) (pourquoi un module partagé : voir son README).

## Variables d'environnement

| Variable | Obligatoire | Défaut | Rôle |
|---|---|---|---|
| `JWT_SECRET` (ou `_FILE`) | oui | — | Secret HS256, ≥ 32 caractères (partagé avec payment-api) |
| `INTERNAL_TOKEN` (ou `_FILE`) | oui | — | Token de l'API interne `/internal/*`, ≥ 16 caractères |
| `POSTGRES_PASSWORD` (ou `_FILE`) | oui | — | Mot de passe DB (`POSTGRES_HOST/PORT/DB/USER` : voir resilience_db) |
| `DATABASE_URL` | non | — | Surcharge complète de l'URL DB (tests : `sqlite://`) |
| `LOGIN_RATE_LIMIT` | non | `10/minute` | Limite de `/login` par IP (`N/second\|minute\|hour\|day`) |
| `TRUSTED_PROXY_HOPS` | non | `1` | Nombre de proxys de confiance devant le service (lecture de `X-Forwarded-For` depuis la droite) |
| `RUN_MIGRATIONS` | non | `true` | Applique Alembic au démarrage (verrou : sûr si payment-api démarre en parallèle) |
| `REGISTER_INITIAL_BALANCE_CENTS` | non | `0` | Solde initial du compte créé par `/register` |
| `ENABLE_DOCS` | non | `false` | Expose `/docs` et `/openapi.json` (dev uniquement) |
| `LOG_LEVEL` | non | `INFO` | Niveau de log |
| `FACE_ID_URL` | non | `http://face-id:8006` | URL du service face-id (réseau `app`) |
| `FACE_INTERNAL_TOKEN` (ou `_FILE`) | non* | — | Token `X-Internal-Token` envoyé à face-id (**même secret SOPS que face-id**). *Sans lui, l'étape visage et l'administration répondent 503 (warning au démarrage) |
| `BACKOFFICE_FACE_REQUIRED` | non | `true` | `false` = mode dégradé (mot de passe seul, répétitions de démo — **jamais** en démo notée) |
| `BACKOFFICE_FACE_TIMEOUT` | non | `2.0` | Délai (s) des appels `verify` / `enrollments` / `revoke` à face-id. **`8` dans le Compose** : dlib (backend `team`) analyse 3 images 640 px par vérification, plusieurs secondes sur le CPU de l'hôte ; si la latence approche encore ce délai en recette, levier côté face-id : `FACE_DETECT_UPSAMPLE=0` |
| `BACKOFFICE_REJECT_COOLDOWN` | non | `30` | Refroidissement (s) après un visage refusé |
| `BACKOFFICE_FAIL_COOLDOWN` | non | `3` | Refroidissement (s) après un mot de passe refusé |
| `BACKOFFICE_MAX_ATTEMPTS` | non | `2` | Échecs tolérés avant verrouillage (« 1 reprise ») |
| `BACKOFFICE_LOCKOUT_SECONDS` | non | `300` | Durée du verrouillage `(identifiant, IP)` |
| `BACKOFFICE_CHALLENGE_TTL` | non | `60` | Durée de vie (s) d'un challenge. **`120` dans le Compose** (chargement à froid de MediaPipe + 3 maintiens de pose) |
| `BACKOFFICE_FAILURE_WINDOW` | non | `900` | Fenêtre (s) au-delà de laquelle un échec est oublié |
| `BACKOFFICE_RATE_LIMIT` | non | `30/minute` | Limite de débit des routes `auth/*` (à étapes) et `admin/*` |
| `BACKOFFICE_BOOTSTRAP_TOKEN` (ou `_FILE`) | non | vide | Secret du bootstrap du premier administrateur. **Vide = bootstrap désactivé** (toujours refusé) |
| `MQTT_HOST` | non | vide | Broker Mosquitto ; vide = LED simplement journalisée (dev/tests) |
| `MQTT_PORT` | non | `1883` | Port du broker |
| `MQTT_USERNAME` | non | `auth` | Compte MQTT (ACL par topic) |
| `MQTT_AUTH_PASSWORD` (ou `_FILE`) | non | vide | Mot de passe MQTT du compte `auth` |

## API du back-office

Contrats : [`docs/contracts.md §5`](../../docs/contracts.md) et CDC §3. `POST /api/v1/login` (comptes de service, front client) est **inchangé** et hors facteur visage.

### Authentification à étapes (v2)

`identify → face → password` ; seul `auth` décide de l'accès, face-id ne renvoie que match/no-match.

```bash
# 1. identifiant : renvoie challenge_id et l'ORDRE des 3 poses, tiré au hasard (CSPRNG) à chaque appel
curl -s -XPOST localhost:8002/api/v1/auth/identify -H 'content-type: application/json' -d '{"username":"op01"}'
#   {"challenge_id":"…","step":"face","expires_in":60,"camera":true,"poses":["droite","face","gauche"]}
# 2. visage : EXACTEMENT 3 frames, dans l'ordre des poses reçues (sinon refus sans appeler face-id)
curl -s -XPOST localhost:8002/api/v1/auth/face -H 'content-type: application/json' \
  -d '{"challenge_id":"…","frames":[{"pose":"droite","image_b64":"…"},{"pose":"face","image_b64":"…"},{"pose":"gauche","image_b64":"…"}]}'
#   {"recognized":true,"step":"password","attempts_left":2,"cooldown":0}
# 3. mot de passe : renvoie le JWT (claim role), réservé aux rôles operator/admin
curl -s -XPOST localhost:8002/api/v1/auth/password -H 'content-type: application/json' -d '{"challenge_id":"…","password":"…"}'
```

- **Refroidissements** (par IP ; `429 cooldown` + `Retry-After` sur `identify`) : **30 s** après un visage refusé (`BACKOFFICE_REJECT_COOLDOWN`), **3 s** après un mot de passe refusé (`BACKOFFICE_FAIL_COOLDOWN`).
- **Verrouillage** : 2 échecs (`BACKOFFICE_MAX_ATTEMPTS`) pour un `(identifiant, IP)` ⇒ `429 locked_out` pendant **300 s**, contrôlé à chaque étape.
- Face-id injoignable ⇒ `503 face_service_unavailable` : le back-office est inaccessible par conception, jamais ouvert par défaut.
- **LED** : chaque étape publie un état sémantique sur MQTT (`idle`, `recognized`, `auth_ok`, `auth_fail`, `not_recognized`) via `MqttLedNotifier` (**fail-open** : un broker en panne n'empêche jamais la connexion, et une panne au démarrage du notifieur n'empêche pas `auth` de démarrer — `led_publish_failed`, WARNING ; un refus du broker à la connexion est journalisé de même, avec le seul code de raison ; dans le Compose, `mosquitto` est une dépendance `required: false`). `GET /api/v1/auth/device` → `{"led_online": true|false|null}` (dernier statut/LWT reçu ; `null` si inconnu, LED simulée ou lien broker perdu).

### Administration des habilitations

`Authorization: Bearer <jwt>` avec le rôle **`admin`** (`401 missing_token|invalid_token`, `403 forbidden`). Le rôle est revalidé en base à chaque appel : un admin rétrogradé perd l'accès immédiatement. Débit : `BACKOFFICE_RATE_LIMIT`.

| Route | Réponses |
|---|---|
| `GET /api/v1/admin/users` | `200 [{username, role, enrolled, stale, enrolled_at, enrolled_by}]` — `enrolled` = enrôlement **utilisable** (`usable` de face-id), `stale` = ligne périmée (réenrôlement requis) |
| `POST /api/v1/admin/users` `{username, password, role}` | `201 {username, role}` ; `409 username_taken` ; `422` (aucun compte bancaire créé) |
| `PATCH /api/v1/admin/users/{u}` `{role}` | `200 {username, role}` ; `404 unknown_user` ; `409 last_admin` |
| `PUT /api/v1/admin/users/{u}/face` `{poses:{face,gauche,droite}}` | `200 {enrolled:true, model_version}` ; `422 enrollment_rejected` (+ `details:[{pose,reason}]`) ; `404 unknown_user` ; `503 face_service_unavailable` |
| `DELETE /api/v1/admin/users/{u}/face` | `204` ; `404 not_enrolled` ; `409 last_admin` |
| `GET /api/v1/admin/users/{u}/face/photos` | `200 {photos:{face,gauche,droite}}` (consultation journalisée par face-id) ; `404 not_enrolled` |

`last_admin` : l'opération (rétrogradation ou révocation du visage) retirerait le **dernier administrateur enrôlé** ; « enrôlé » se lit auprès de face-id et ne compte que les enrôlements `usable` (une ligne d'un autre modèle ou v1 ne permet pas de se connecter).

### Bootstrap du premier administrateur

Sans administrateur enrôlé, personne ne passe l'étape visage. Si `BACKOFFICE_BOOTSTRAP_TOKEN` est défini :

- `GET /api/v1/auth/bootstrap` → `{"required": true}` ⇔ aucun admin à l'enrôlement **utilisable** **et** token configuré (`503` si face-id est injoignable).
- `POST /api/v1/auth/bootstrap` `{token, username, password, poses}` → `201 {username, role:"admin"}` ; `403 bootstrap_denied` (token faux, bootstrap non requis ou désactivé) ; `422 enrollment_rejected`. Limité à `5/minute`, token comparé en temps constant. Un compte existant n'est repris que s'il est `operator` ou `admin` (mot de passe et rôle `admin` mis à jour) ; un compte `customer` existant est refusé (`403 bootstrap_denied`, rien n'est modifié). **Si l'enrôlement échoue, la création est annulée** : le gabarit éventuellement déjà stocké par face-id est d'abord révoqué (sauf s'il préexistait), puis le compte est supprimé ou son état précédent restauré ; une panne de ce rollback est journalisée (`backoffice_bootstrap`, ERROR) et l'erreur d'origine (422/503) reste celle renvoyée.

Événements : `admin_user_created`, `admin_role_changed`, `admin_face_enrolled`, `admin_face_revoked`, `backoffice_bootstrap` (champ `user` = compte ciblé, le message nomme l'acteur ; jamais de mot de passe, token ni image).

## Lancement local

```bash
# depuis la racine du dépôt (python >= 3.12)
python -m venv /tmp/rc-be && source /tmp/rc-be/bin/activate
pip install -e "libs/python/resilience_common[fastapi]" -e libs/python/resilience_db
pip install -e services/auth
export JWT_SECRET="$(openssl rand -hex 32)" INTERNAL_TOKEN="$(openssl rand -hex 16)"
export DATABASE_URL="sqlite:///./dev-auth.db"          # ou POSTGRES_HOST/POSTGRES_PASSWORD
uvicorn auth_service.main:create_app --factory --port 8002 --no-access-log
curl -s localhost:8002/health
```

Seed des comptes de test (fictifs) : `SEED_PASSWORD='...' python -m resilience_db.seed` → `demo01`…`demo05`.

### Docker

Le **contexte de build est la racine du dépôt** (le Dockerfile installe les libs partagées) :

```bash
docker build -f services/auth/Dockerfile -t resilience/auth:dev .
docker run --rm --read-only --cap-drop ALL --network <réseau_data_et_app> \
  -e JWT_SECRET=... -e INTERNAL_TOKEN=... -e POSTGRES_PASSWORD=... resilience/auth:dev
```

L'image : `python:3.12-slim`, build multi-étapes (aucun outil de build ni code de test dans l'image finale), utilisateur `10001` sans shell, aucun secret, `HEALTHCHECK` sur `/health`, 1 worker, access-logs uvicorn désactivés pour que stdout reste 100 % JSON (Promtail).

## Tests

```bash
pip install -r services/auth/requirements-dev.txt -e libs/python/resilience_db[test]
pytest services/auth
```

- **Base SQLite en mémoire** (fixture) : suffit pour les règles métier ; les schémas viennent des vrais modèles et un test rejoue les vraies migrations Alembic. La validation sur **PostgreSQL réel** est couverte côté `payment-api` (test d'intégration optionnel, `TEST_POSTGRES_URL`) et a été vérifiée manuellement avec les images Docker.
- Un test par règle métier et par contrat (voir la matrice des critères dans le CDC).
- Face-id, MQTT et l'horloge sont **injectables** (`create_app(face_client=…, face_verifier=…, led_notifier=…, clock=…)`) : aucun réseau ni matériel dans les tests (`test_auth_stepped.py`, `test_face_client.py` via `httpx.MockTransport`, `test_led_mqtt.py`, `test_admin.py` avec un `FakeFaceClient` en mémoire).

## Exploitation

- **Remédiation** (`auth_abuse`) : `POST /internal/tighten-rate-limit` avec `X-Internal-Token` et `{"factor": 0.5}`. Retour à la normale : `POST /internal/reset-rate-limit`. Ces routes ne doivent **pas** être routées par le WAF.
- **Prérequis WAF** : transmettre l'IP source réelle dans `X-Forwarded-For` (le service lit l'entrée la plus à droite). Si plusieurs proxys sont chaînés devant le service, ajuster `TRUSTED_PROXY_HOPS`.
- **Logs d'alerte Loki** : `{service="auth"} | json | event="auth_login_failed"`, `event="auth_rate_limited"`.

## Écarts et points d'attention

- Métriques HTTP conformes : `resilience_common.metrics.instrument(app, "auth")` produit désormais exactement `resilience_http_requests_total{service,method,path,status}` et `resilience_http_request_duration_seconds{service,method,path}` (contrat §2). Le test `test_http_metrics_follow_contract_names_and_labels` est **actif et vert** (plus de `xfail`).
- Le contrat §1 évoque un middleware qui injecte `request_id`/`client_ip`/`http_*` ; `resilience_common` ne le fournit pas, il est donc dans `observability.py` (copie identique dans payment-api, à remonter dans la lib).
- L'exemple de log du contrat montre `http_path:"/login"` ; le service journalise le chemin réel `/api/v1/login`.
- En cas de panne DB, auth journalise une erreur avec l'événement générique `log` : `db_error` et `resilience_db_errors_total` sont réservés à payment-api par le contrat.
