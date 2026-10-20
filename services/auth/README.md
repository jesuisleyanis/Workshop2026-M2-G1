# services/auth

Service d'authentification FastAPI (JWT HS256, bcrypt, rate-limit slowapi) de la plateforme fictive RESILIENCE-ALPHA. Cadrage, exigences et critères d'acceptation : [`CAHIER-DES-CHARGES.md`](CAHIER-DES-CHARGES.md). Contrats transverses : [`docs/contracts.md`](../../docs/contracts.md).

- **Port interne** `8002` — **réseau** `app` (+ `data` pour PostgreSQL) — **nom Compose** `auth`

## Architecture interne

```
requête ─► RequestContextMiddleware ─► route FastAPI ─► SQLAlchemy ─► PostgreSQL (resilience_db)
              (request_id, client_ip)      │  ▲
                                           │  └─ slowapi (rate-limit /login, limite dynamique)
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
│   ├── security.py            # création du JWT, comparaison du token interne
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

## Exploitation

- **Remédiation** (`auth_abuse`) : `POST /internal/tighten-rate-limit` avec `X-Internal-Token` et `{"factor": 0.5}`. Retour à la normale : `POST /internal/reset-rate-limit`. Ces routes ne doivent **pas** être routées par le WAF.
- **Prérequis WAF** : transmettre l'IP source réelle dans `X-Forwarded-For` (le service lit l'entrée la plus à droite). Si plusieurs proxys sont chaînés devant le service, ajuster `TRUSTED_PROXY_HOPS`.
- **Logs d'alerte Loki** : `{service="auth"} | json | event="auth_login_failed"`, `event="auth_rate_limited"`.

## Écarts et points d'attention

- Métriques HTTP conformes : `resilience_common.metrics.instrument(app, "auth")` produit désormais exactement `resilience_http_requests_total{service,method,path,status}` et `resilience_http_request_duration_seconds{service,method,path}` (contrat §2). Le test `test_http_metrics_follow_contract_names_and_labels` est **actif et vert** (plus de `xfail`).
- Le contrat §1 évoque un middleware qui injecte `request_id`/`client_ip`/`http_*` ; `resilience_common` ne le fournit pas, il est donc dans `observability.py` (copie identique dans payment-api, à remonter dans la lib).
- L'exemple de log du contrat montre `http_path:"/login"` ; le service journalise le chemin réel `/api/v1/login`.
- En cas de panne DB, auth journalise une erreur avec l'événement générique `log` : `db_error` et `resilience_db_errors_total` sont réservés à payment-api par le contrat.
