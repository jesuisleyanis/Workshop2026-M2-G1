# services/payment-api

API de paiement **fictive** (comptes, virements, historique) de la plateforme RESILIENCE-ALPHA. Cadrage, règles métier et critères d'acceptation : [`CAHIER-DES-CHARGES.md`](CAHIER-DES-CHARGES.md). Contrats transverses : [`docs/contracts.md`](../../docs/contracts.md).

- **Port interne** `8001` — **réseau** `app` (+ `data` pour PostgreSQL) — **nom Compose** `payment-api`

## Architecture interne

```
requête ─► RequestContextMiddleware ─► dépendance current_user (JWT HS256 + utilisateur en base)
              (request_id, client_ip)        │
                                             ▼
                                 route ──► ledger.transfer() ──► SQLAlchemy ──► PostgreSQL (resilience_db)
                                    │         (règles métier,       (SELECT … FOR UPDATE ordonné,
                                    │          lève Rejection)       1 transaction SQL)
                                    ├─► logs JSON  (transaction_created / transaction_rejected / db_error)
                                    └─► métriques  (resilience_transactions_total, resilience_db_errors_total, HTTP)
```

`ledger.py` ne connaît pas HTTP : il lève `Rejection(status, code, message)` que la route traduit en réponse + log + métrique — ce qui rend les règles testables isolément.

```
services/payment-api/
├── CAHIER-DES-CHARGES.md
├── README.md
├── Dockerfile                 # multi-étapes, slim, non-root, HEALTHCHECK /health
├── Dockerfile.dockerignore    # contexte de build minimal
├── requirements.txt           # dépendances runtime épinglées (source unique, lue par pyproject)
├── requirements-dev.txt       # + pytest, httpx, ruff
├── pyproject.toml
├── src/payment_api/
│   ├── main.py                # create_app() : routes, dépendance current_user, handlers d'erreurs, lifespan
│   ├── ledger.py              # règles métier du virement (solde, propriété, devise, verrous)
│   ├── security.py            # validation du JWT (algorithme épinglé, exp/sub requis)
│   ├── config.py              # Settings.from_env()
│   ├── schemas.py             # modèles Pydantic (montants en StrictInt)
│   └── observability.py       # contexte de requête, filtre de logs, format d'erreur contrat
└── tests/                     # pytest, SQLite en mémoire (+ 1 test PostgreSQL optionnel)
```

## Persistance : choix du module partagé `resilience_db`

Le schéma (`users`, `accounts`, `transactions`), la config de connexion, les migrations Alembic et le seed vivent dans [`libs/python/resilience_db`](../../libs/python/resilience_db/README.md), installé comme `resilience_common`. **Justification** : `auth` et `payment-api` sont déployés séparément mais partagent la même base ; une copie des modèles par service créerait deux sources de vérité susceptibles de diverger et deux chaînes de migrations en conflit. Contrepartie : build Docker avec la racine du dépôt pour contexte.

## Variables d'environnement

| Variable | Obligatoire | Défaut | Rôle |
|---|---|---|---|
| `JWT_SECRET` (ou `_FILE`) | oui | — | Secret HS256 **identique à celui d'auth**, ≥ 32 caractères |
| `POSTGRES_PASSWORD` (ou `_FILE`) | oui | — | Mot de passe DB (`POSTGRES_HOST/PORT/DB/USER` : voir resilience_db ; défauts `postgres`/`5432`/`resilience`/`resilience`) |
| `DATABASE_URL` | non | — | Surcharge complète de l'URL DB (tests : `sqlite://`) |
| `TRUSTED_PROXY_HOPS` | non | `1` | Proxys de confiance devant le service (lecture de `X-Forwarded-For` depuis la droite) |
| `RUN_MIGRATIONS` | non | `true` | Applique Alembic au démarrage (verrou : sûr si auth démarre en parallèle) |
| `ENABLE_DOCS` | non | `false` | Expose `/docs` (dev uniquement) |
| `LOG_LEVEL` | non | `INFO` | Niveau de log |
| `SCHEDULER_ENABLED` | non | `true` | Tâche de fond des virements programmés (#48) |
| `SCHEDULER_INTERVAL_S` | non | `60` | Intervalle entre deux passes de l'exécuteur |
| `STATUS_CACHE_S` | non | `2` | Durée de cache de `GET /api/v1/status`, bornée à [0,5 ; 30] s (refus au démarrage sinon) |

## Lancement local

```bash
# depuis la racine du dépôt (python >= 3.12)
python -m venv /tmp/rc-be && source /tmp/rc-be/bin/activate
pip install -e "libs/python/resilience_common[fastapi]" -e libs/python/resilience_db
pip install -e services/payment-api
export JWT_SECRET="$(openssl rand -hex 32)" DATABASE_URL="sqlite:///./dev-pay.db"
SEED_PASSWORD='...' python -m resilience_db.seed        # demo01..demo05
uvicorn payment_api.main:create_app --factory --port 8001 --no-access-log
```

Obtenir un jeton : `POST /api/v1/login` sur le service `auth` (même `JWT_SECRET`), puis `curl -H "Authorization: Bearer $TOKEN" localhost:8001/api/v1/accounts`.

### Docker

Le **contexte de build est la racine du dépôt** :

```bash
docker build -f services/payment-api/Dockerfile -t resilience/payment-api:dev .
docker run --rm --read-only --cap-drop ALL --network <réseau_data_et_app> \
  -e JWT_SECRET=... -e POSTGRES_PASSWORD=... resilience/payment-api:dev
```

Image : `python:3.12-slim`, multi-étapes, utilisateur `10001` sans shell, aucun secret, `HEALTHCHECK` sur `/health`, access-logs uvicorn désactivés (stdout 100 % JSON pour Promtail).

## Tests

```bash
pip install -r services/payment-api/requirements-dev.txt -e libs/python/resilience_db[test]
pytest services/payment-api
```

- **SQLite en mémoire** pour les tests unitaires (fixture : schéma créé depuis les vrais modèles ; un test rejoue les vraies migrations Alembic). `FOR UPDATE` y est ignoré, d'où :
- **Test d'intégration PostgreSQL optionnel** (ignoré par défaut) : 6 virements concurrents de 300 EUR sur 1 000 EUR ⇒ exactement 3 acceptés, 3 refusés, solde exact.
  ```bash
  TEST_POSTGRES_URL=postgresql+psycopg://resilience:***@127.0.0.1:5432/<base_jetable> pytest services/payment-api -k postgres
  ```
- Les logs sont vérifiés via le **vrai formatter** de `resilience_common` ; les métriques via le registre Prometheus (delta avant/après).

## Exploitation

- **Transaction de contrôle (`verify_tx`)** : login `auth` → `POST /api/v1/transactions` entre deux comptes seedés → attendre `201` (code retour 0) / sinon 1.
- **Alertes Loki** : `{service="payment-api"} | json | event="db_error"` ; ratio `transaction_rejected` / `transaction_created`.
- **Notifications (#49)** : écrites dans la **même transaction** que l'événement (`notifications.notify`, pas de commit propre) ; sur le chemin chaud du trafic normal (~1 virement/s, demo01↔demo02) cela ajoute seulement deux lignes au commit du virement externe (pas de flush ni de requête en plus) ; la rétention (100 par client) est appliquée **hors chemin chaud** par la tâche de fond périodique (`prune_all`, clients au-delà de 100 seulement) et à la lecture. Le badge lit `GET /notifications/unread-count` (un `COUNT`). Pas de nouvelle métrique ni de label.
- **Virements programmés (#48)** : une tâche de fond par réplique (`lifespan`) appelle `schedules.run_due` toutes les `SCHEDULER_INTERVAL_S`. Chaque échéance est **réservée** (`scheduled_runs`, `UNIQUE(scheduled_id, run_on)`) dans la même transaction que l'avancement de `next_run_on`, puis exécutée par `ledger.transfer` : deux répliques ou un redémarrage par la remédiation (`restart_service`) ne peuvent pas l'exécuter deux fois ; un arrêt brutal entre réservation et virement la laisse en `pending` (au plus une fois). BDD indisponible pendant un incident : la passe échoue, journalisée, et reprend au tour suivant (rattrapage limité aux 31 derniers jours : une échéance plus ancienne est sautée, jamais débitée ; une reprise après pause repart de la première échéance à venir ; verrou de ligne contre une annulation concurrente ; une erreur BDD après réservation est enregistrée `failed/internal_error`). Aucune programmation n'est seedée : la baseline ML n'est pas modifiée.
- **Plafond mensuel (#46)** : `accounts.monthly_limit_cents` NULL = pas de plafond. Les comptes de **service** `demo01`/`demo02` (source de `verify_tx`, du trafic normal ~1 virement/s et de `service_flood`) ne sont **jamais** plafonnés : un plafond les ferait passer en `409` en quelques heures, fausserait le ratio 4xx de la baseline ML et ferait échouer la vérification de reprise (test `test_verify_tx_service_account_is_never_capped_even_after_heavy_traffic`). Sans plafond, le ledger ne calcule rien : aucune requête ajoutée sur ces comptes à fort trafic. Clients de démo plafonnés : `demo03`+ (`SEED_MONTHLY_LIMIT_CENTS`, 800 € : sous le solde de 1 000 €, le plafond se déclenche avant le solde insuffisant ; clients seedés avant #46 rattrapés par `make seed`).
- **Catégories (#44)** : `category` n'ajoute aucun label de métrique ni de feature ML ; le trafic normal (`scripts/gen_normal_traffic.py`) envoie des catégories variées **sans changer** sa séquence d'actions (catégorie dérivée du montant), donc le vecteur §2 du collector (débits, ratios 4xx/5xx, latence) est inchangé — pas de faux positif attendu du détecteur. À confirmer en recette en rejouant le trafic normal contre le modèle (`ml/`). Après la migration `0004`, un dump **antérieur** restaurerait un schéma sans `category` : le scénario `data_corruption` prend son dump sain juste avant l'injection (étape 1 de `attacks/run.sh`, idem `tests/e2e`), mais tout dump conservé d'avant le déploiement est à refaire (`pg_backup.yml`).
- **`GET /api/v1/status`** (public, via WAF) : `503 degraded` ⇔ même test BDD que `/ready` (`_db_reachable`), servi par un cache **à vol unique** (`status.py`) : un seul rafraîchissement à la fois, les requêtes concurrentes reçoivent la dernière valeur. Effet sur la baseline ML : **aucun** — la route est exclue de `resilience_http_*` comme `/ready` (les features du collector agrègent tous les chemins, des 503 servis en cache fausseraient le ratio 5xx et la latence) ; elle reste visible dans les logs WAF. Le front ne l'appelle qu'en mode « perturbé » (5 s par client).
- **`/ready` 503** ⇒ la DB est injoignable (`/health` reste 200 : le conteneur n'est pas tué à tort, la remédiation décide).

## Écarts et points d'attention

- Métriques HTTP conformes : `resilience_common.metrics.instrument(app, "payment-api")` produit désormais exactement `resilience_http_requests_total{service,method,path,status}` et `resilience_http_request_duration_seconds{service,method,path}` (contrat §2). Le test `test_http_metrics_follow_contract_names_and_labels` est **actif et vert** (plus de `xfail`).
- Le middleware de contexte de requête (`request_id`, `client_ip`, `http_*`) prévu par le contrat n'existe pas dans `resilience_common` : il est dans `observability.py` (copie identique dans `auth`, à remonter dans la lib).
- L'exemple de log du contrat montre `http_path:"/transactions"` ; le service journalise le chemin réel `/api/v1/transactions`.
- Un corps mal typé (ex. `amount_cents` flottant) est un `422 validation_error` **sans** event `transaction_rejected` ; les refus de règles métier (montant ≤ 0, solde, comptes) en émettent un.
