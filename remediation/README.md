# Moteur de remédiation

Automate de reprise autonome de RESILIENCE-ALPHA : il reçoit un événement d'anomalie, applique la table de décision, exécute les actions, **prouve** le retour à la normale avec `scripts/verify_tx`, puis clôt l'incident (ou escalade). Tout est diffusé en temps réel au dashboard.

- Quoi / pourquoi / modèle de privilèges / critères d'acceptation : [`CAHIER-DES-CHARGES.md`](CAHIER-DES-CHARGES.md)
- Contrats d'interface : [`../docs/contracts.md`](../docs/contracts.md) (§3 événement d'anomalie, §4 table de décision)

Stack : Python 3.12, FastAPI, httpx, SQLite, ansible-runner, `resilience_common` (lib partagée du monorepo).

## Arborescence

```
remediation/
├── main.py                 API FastAPI (create_app / app_factory), auth, middleware, endpoints
├── engine.py               RemediationEngine : cycle d'un incident, garde-fous, vérification
├── decision.py             Chargement + validation de decision_table.yml (schéma + invariants de sécurité)
├── decision_table.yml      Table incident -> actions (source de vérité, contrat §4)
├── models.py               IncomingEvent (AnomalyEvent + source_ip) et utilitaires de dates
├── config.py               Settings.from_env() : variables d'environnement
├── journal.py              Journal SQLite : incidents, actions, vérifications, timeline
├── timeline.py             Broker pub/sub + génération des trames SSE
├── verify.py               ScriptVerifier : exécute scripts/verify_tx
├── http_metrics.py         Métriques HTTP du contrat §2
├── actions/
│   ├── __init__.py         REGISTRY (type -> classe) et build_action()
│   ├── base.py             Action, ActionContext, ActionResult, ActionError, ActionParamError
│   ├── docker.py           restart_service, recreate_service
│   ├── docker_proxy.py     Client du docker-socket-proxy (liste blanche méthode+chemin)
│   ├── waf.py              waf_block_ip, waf_blacklist_ip, confirm_waf_block
│   ├── rate_limit.py       tighten_rate_limit (API interne du service auth)
│   ├── postgres.py         restore_pg_dump
│   ├── ops.py              dry_run_report, notify_operator
│   └── runner.py           Port Ansible (ansible-runner) + liste blanche de playbooks
├── proxy/
│   └── haproxy.cfg         Config stricte (4 verbes) pour le docker-socket-proxy
├── tests/                  pytest (voir « Tester »)
├── Dockerfile              Image durcie (multi-stage, non-root uid 10001)
├── Dockerfile.dockerignore
├── pytest.ini              pythonpath = . ; testpaths = tests
├── requirements.txt        Dépendances d'exécution
└── requirements-dev.txt    + pytest
```

## Architecture interne

```
POST /events ──► main.py (auth Bearer) ──► engine.handle_event ──► journal (incident) + timeline
                                              │  admission : replay (event_id) / duplicate (clé) / cooldown
                                              ▼
                                   tâche asyncio _run(incident)
                                              │
              decision.py ◄── règle (table) ──┤
                                              ▼
                        _attempt : pour chaque action de la règle, dans l'ordre
                                   build_action(type, params) ──► actions/* ──► docker-socket-proxy | Ansible | auth | Loki
                                              │   après action mutante OK (et après la dernière) :
                                              ▼
                                   verify.ScriptVerifier ──► scripts/verify_tx (exit 0 = OK)
                                              │
                       OK ► _close (MTTD/MTTR) ── KO ► action suivante ── épuisé ► tentative suivante ── max_attempts ► _escalate
                                              │
                      chaque étape ──► journal.add_timeline ──► Broker.publish ──► GET /stream (SSE) ──► dashboard
```

### Modules

- **`main.py`** : `create_app(settings, table, services, http_transport)` assemble l'ensemble (injection pour les tests) ; `app_factory()` est le point d'entrée uvicorn (`--factory`) et quitte avec un message clair si la table est invalide. Gère : middleware (`X-Request-ID`, logs d'accès JSON, métriques HTTP), handlers d'erreur au format du contrat, dépendance d'authentification `require_token` (Bearer, `hmac.compare_digest`, fail closed), `lifespan` (marque les incidents orphelins `interrupted` au démarrage, annule les tâches à l'arrêt). `/docs`, `/redoc`, `/openapi.json` sont désactivés.
- **`engine.py`** : `RemediationEngine`. `handle_event` fait l'admission (rejeu d'`event_id`, doublon de clé `incident_type:service`, cooldown), crée l'incident et lance `_run` en tâche de fond. `_remediate` boucle sur `max_attempts` (avec attente du cooldown entre tentatives) ; `_attempt` exécute les actions de la règle dans l'ordre et vérifie après chaque action mutante réussie et après la dernière ; `_execute` gère le dry-run (plan seulement pour une action mutante), le verrou `_action_lock` (une action mutante à la fois), le timeout, la métrique `remediation_actions_total`, les gauges MTTD/MTTR (bornées à 20 incidents), le journal et la timeline ; `_verify` rejoue `verify_tx` jusqu'à `VERIFY_RETRIES` fois ; `_close`, `_finish_dry_run`, `_escalate` produisent les trois issues. Les dépendances externes sont regroupées dans `Services` (http, docker, runner, verifier) pour être mockées.
- **`decision.py`** : modèles Pydantic stricts (`extra="forbid"`) de la table (`DecisionTable`, `Defaults`, `Rule`, `ActionSpec`) ; `load_decision_table` (`yaml.safe_load`). La validation vérifie : version `1.0`, une règle exacte par `IncidentType` (ni doublon, ni manquant), actions connues et paramètres valides, escalade non mutante, et les invariants de sécurité (`data_corruption` contient `restore_pg_dump` et jamais `restart/recreate` ; `restore_pg_dump` réservé à `data_corruption` ; `unknown` sans action mutante). Erreur → `DecisionTableError`.
- **`actions/`** : une action = `type`, `params` (issus de la table), `mutating`, `check_params` (validation au chargement ET à l'exécution), `execute`, `plan` (dry-run). `docker_proxy.py` n'autorise que `GET /_ping`, `GET /containers/json`, `GET /containers/{id}/json`, `POST /containers/{id}/restart` (+ stop/rename/create/start/DELETE si `DOCKER_PROXY_ALLOW_RECREATE`). `waf.py` résout l'IP (`source_ip` de l'événement), refuse les IP protégées (`NEVER_BLOCK_IPS`, loopback…) et passe par le playbook `waf_deny_ip.yml`. `runner.py` n'accepte que `waf_deny_ip.yml` et `pg_restore.yml`. `ops.py` : `dry_run_report` (journalisation) et `notify_operator` (log `remediation_failed` + webhook optionnel).
- **`journal.py`** : SQLite (`INCIDENTS_DB`), accès protégé par verrou. Tables `incidents`, `actions`, `verifications`, `timeline`. Fournit l'idempotence (`incident_for_event`), le cooldown (`last_action_at`), la reprise après redémarrage (`recover_orphans`) et le rejeu de timeline (`timeline_since`, `latest_timeline_id`). Statuts : `in_progress`, puis `closed | escalated | dry_run | interrupted`.
- **`timeline.py`** : `Broker` (file `asyncio.Queue` de 1000 par abonné ; un abonné trop lent est déconnecté et se reconnecte), `frame()` (trame SSE), `sse_stream()` (abonnement *avant* le rejeu, donc sans trou ni doublon ; commentaire `: keepalive` si inactif).
- **`verify.py`** : `ScriptVerifier` lance `VERIFY_TX_PATH` sans shell, avec timeout (`VERIFY_TIMEOUT_S`) ; exit 0 = OK ; renvoie `VerifyResult(ok, rc, detail)` (dernière ligne de sortie, 200 caractères max).
- **`models.py`** : `IncomingEvent` = `AnomalyEvent` (`resilience_common`) + `source_ip` optionnel (une IP littérale) ; champs inconnus ignorés.
- **`http_metrics.py`** : `resilience_http_requests_total{service,method,path,status}` et `resilience_http_request_duration_seconds{service,method,path}` (chemin = gabarit de route, cardinalité bornée).

## Endpoints

API sur le port **8005** (interne, réseau `app` ; jamais publié). Sauf sondes, tout exige `Authorization: Bearer <REMEDIATION_TOKEN>`.

| Méthode | Chemin | Auth | Description |
|---|---|---|---|
| `POST` | `/events` | oui | Reçoit un `AnomalyEvent` (+ `source_ip` optionnel). `202` `{incident_id, decision, dry_run, detail}` avec `decision` ∈ `started`, `duplicate`, `replayed`, `cooldown`. `422` si le corps est invalide. |
| `GET` | `/incidents?limit=50` | oui | Derniers incidents (`limit` 1 à 500). |
| `GET` | `/incidents/{incident_id}` | oui | Détail : incident + `actions` + `verifications` + `timeline`. `404 incident_not_found`. |
| `GET` | `/decision-table` | oui | Table de décision chargée (JSON). |
| `GET` | `/stream` | oui | Timeline temps réel (SSE). Voir ci-dessous. |
| `GET` | `/health` | non | Liveness : `{"status": "ok"}`. |
| `GET` | `/ready` | non | Readiness : `200`/`503` avec `checks` = `decision_table`, `journal`, `auth_configured`, `docker_socket_proxy` (ping du proxy). |
| `GET` | `/metrics` | non | Métriques Prometheus (`resilience_remediation_actions_total`, `resilience_mttd_seconds`, `resilience_mttr_seconds`, métriques HTTP). |

Codes d'erreur d'authentification : `401 unauthorized` (+ `WWW-Authenticate: Bearer`), `503 auth_not_configured` si le token est absent ou fait moins de 16 caractères (fail closed). Corps d'erreur : `{"error": {"code", "message", "request_id"}}`.

Exemple :

```bash
curl -s -X POST http://localhost:8005/events \
  -H "Authorization: Bearer $REMEDIATION_TOKEN" -H 'Content-Type: application/json' \
  -d '{"service":"payment-api","anomaly_score":0.87,"threshold":0.6,
       "incident_type":"service_flood","source_ip":"203.0.113.50"}'
```

### Timeline temps réel pour le dashboard : `GET /stream` (SSE)

Le dashboard consomme **Server-Sent Events** (pas de WebSocket) sur `GET /stream`.

- Paramètres : `incident_id` (filtre sur un incident), `since` (id de timeline à partir duquel rejouer), `follow` (défaut `true` ; `false` = rejeu puis fermeture). Header `Last-Event-ID` pris en compte à la reconnexion si `since` est absent.
- Première connexion sans `since` : les 50 derniers événements, pour reconstruire l'état.
- Trame : `retry: 3000`, puis pour chaque événement :
  ```
  id: <id de timeline>
  event: timeline
  data: {"id":…, "incident_id":…, "incident_type":…, "ts":"…Z", "phase":…, "status":…, "message":…, "data":{…}}
  ```
  Commentaire `: keepalive` toutes les `SSE_KEEPALIVE_S` secondes d'inactivité.
- `phase` : `detection` → `decision` → `action` → `verification` → `closure` | `escalation`. `status` : `info`, `running`, `ok`, `ko`, `failed`, `skipped`, `dry_run`.
- Réponse : `text/event-stream`, `Cache-Control: no-cache`, `X-Accel-Buffering: no`.
- L'`id` SSE est l'id SQLite de la timeline : persistant, croissant, rejouable après reconnexion ou redémarrage du moteur.
- Un `EventSource` navigateur ne peut pas poser de header : le dashboard passe par son reverse-proxy nginx (`GET /remediation/stream` → `/stream`) qui injecte `Authorization` (variable `REMEDIATION_AUTH_HEADER` du conteneur dashboard). Voir [`../dashboard/README.md`](../dashboard/README.md).

## Variables d'environnement

Lues par `config.py` (`Settings.from_env`). **Aucun secret n'a de valeur par défaut.** Un secret peut être fourni via `<NOM>_FILE` (chemin d'un fichier, prioritaire sur `<NOM>`), typiquement un secret SOPS/age déchiffré et monté en lecture seule.

| Variable | Défaut | Rôle |
|---|---|---|
| `REMEDIATION_TOKEN` / `REMEDIATION_TOKEN_FILE` | — (obligatoire, ≥ 16 car.) | Bearer exigé sur l'API. Absent/court = routes protégées en `503` (fail closed). |
| `INTERNAL_TOKEN` / `INTERNAL_TOKEN_FILE` | — | Token de l'API interne du service `auth` (`tighten_rate_limit`) ; absent = l'action échoue. |
| `DOCKER_PROXY_URL` | `http://docker-socket-proxy:2375` | URL du docker-socket-proxy. |
| `DOCKER_PROXY_ALLOW_RECREATE` | `false` | Autorise `recreate_service` (nécessite un proxy élargi). |
| `RESTARTABLE_SERVICES` | `payment-api,auth,front` | Liste blanche (CSV) des services redémarrables/recréables. |
| `AUTH_URL` | `http://auth:8002` | Base de l'API du service auth. |
| `LOKI_URL` | `http://loki:3100` | Base de Loki (`confirm_waf_block`). |
| `NOTIFY_WEBHOOK_URL` | — | Webhook optionnel appelé à l'escalade. |
| `DECISION_TABLE` | `<dossier>/decision_table.yml` | Chemin de la table de décision. |
| `INCIDENTS_DB` | `incidents.db` | Fichier SQLite du journal (`/var/lib/remediation/incidents.db` dans l'image). |
| `INCIDENTS_EXPORT_PATH` | `/var/lib/remediation/export/incidents.json` | Fichier produit par `export_journal.py` (CLI uniquement). |
| `VERIFY_TX_PATH` | `scripts/verify_tx` | Script de vérification (`/opt/scripts/verify_tx` dans l'image). |
| `VERIFY_TIMEOUT_S` | `30` | Timeout d'une exécution de `verify_tx`. |
| `VERIFY_RETRIES` | `5` | Essais de `verify_tx` après une action (min. 1). |
| `VERIFY_INTERVAL_S` | `3` | Pause entre deux essais. |
| `ACTION_TIMEOUT_S` | `300` | Timeout d'une action. |
| `ANSIBLE_PRIVATE_DATA_DIR` | `/opt/ansible` | Répertoire ansible-runner (playbooks sous `project/`). |
| `REMEDIATION_DRY_RUN` | `false` | Force le dry-run (ne peut jamais le désactiver s'il est actif dans la table). Valeurs vraies : `1`, `true`, `yes`, `on`. |
| `NEVER_BLOCK_IPS` | `127.0.0.1,::1,192.168.137.1` | IP jamais bloquées (CSV). |
| `SSE_KEEPALIVE_S` | `15` | Intervalle des keepalive SSE. |

Les paramètres de la table de décision (`cooldown_seconds`, `max_attempts`, `dry_run`) ne sont **pas** des variables d'environnement : ils viennent de `decision_table.yml`.

Les logs sont produits par `resilience_common.get_logger("remediation")` (JSON, contrat §1) ; `config.py` ne lit aucune variable pour leur niveau.

## Lancer

### En local (développement)

Depuis la racine du dépôt (`/Users/yanis/EPSI/M2/workshop`) :

```bash
cd remediation
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ../libs/python/resilience_common
pip install -r requirements.txt

export REMEDIATION_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
export INTERNAL_TOKEN="dev-internal-token-change-me"
export REMEDIATION_DRY_RUN=true        # recommandé hors stack : aucune action mutante
export INCIDENTS_DB=/tmp/incidents.db
export VERIFY_TX_PATH="$PWD/../scripts/verify_tx"
uvicorn --factory main:app_factory --host 127.0.0.1 --port 8005
```

Hors stack Docker, `/ready` renverra `503` tant que le docker-socket-proxy n'est pas joignable (check `docker_socket_proxy`) ; l'API reste utilisable.

### En conteneur

Le service `remediation` est défini dans `infra/compose/docker-compose.yml` (réseau `app` uniquement, aucun `ports:`), derrière `docker-socket-proxy`. Image construite avec le contexte à la **racine du dépôt** (la lib partagée y est copiée) :

```bash
docker build -f remediation/Dockerfile -t resilience/remediation .
```

L'image tourne en non-root (uid 10001), n'embarque que le code, `decision_table.yml` et `actions/`, expose 8005 et a un `HEALTHCHECK` sur `/health`. Le point d'entrée est `uvicorn --factory main:app_factory`. En stack : `make up`.

### Exploitation : export du journal pour l'assistant

L'assistant RAG n'indexe qu'une **copie** JSON du journal (jamais l'API ni la base). Commande à lancer à la demande (aucun hook dans la boucle de remédiation) :

```bash
docker compose exec remediation python export_journal.py [--db PATH] [--out PATH] [--limit N]
# -> 12 incident(s) exporté(s) vers /var/lib/remediation/export/incidents.json
```

- Écrit `{"exported_at": "...", "incidents": [<GET /incidents/{id}> ...]}` (incident complet avec `actions`, `verifications`, `timeline`, les `--limit` plus récents, 200 par défaut), UTF-8.
- Base ouverte en **lecture seule** (`file:...?mode=ro`) ; base absente = code retour `2`, aucune base vide créée.
- Écriture **atomique** (temporaire dans le même dossier + `os.replace`) : l'assistant ne lit jamais un fichier partiel.
- `/var/lib/remediation/export` est le volume nommé `incidents-export`, monté en `:ro` sur l'assistant (`/data/incidents`). Ré-indexation complète : `make assistant-reindex` (voir [`../assistant/README.md`](../assistant/README.md)).

## Tester

Les tests mockent tout l'extérieur (proxy Docker, Ansible, `verify_tx`, HTTP, horloge) : aucun Docker ni réseau requis.

```bash
cd remediation
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e /Users/yanis/EPSI/M2/workshop/libs/python/resilience_common
pip install -r requirements-dev.txt
pytest -q
```

`pytest.ini` fixe `pythonpath = .` et `testpaths = tests`. `make test-py` lance aussi ce dossier (avec le venv adéquat).

| Fichier | Couvre |
|---|---|
| `tests/test_decision_table.py` | Chargement/validation de la table, invariants disponibilité vs corruption, `unknown` sans action destructive, paramètres dangereux. |
| `tests/test_engine.py` | Séquences par type, vérification/MTTD/MTTR, cooldown, dédoublonnage, idempotence, `max_attempts`/escalade, dry-run, IP protégées, liste blanche de services, logs et métriques du contrat, couverture de la timeline. |
| `tests/test_actions.py` | Catalogue d'actions, liste blanche du client Docker, recreate + rollback, `tighten_rate_limit`, `confirm_waf_block`, `notify_operator`, validation des paramètres, liste blanche de playbooks, contrat de `verify_tx`, reprise des incidents orphelins. |
| `tests/test_api.py` | Authentification (401, token en query refusé, fail closed), `POST /events` bout en bout, erreurs au format du contrat, `/incidents`, `/decision-table`, `/stream` avec `Last-Event-ID`, sondes, `/metrics`. |
| `tests/test_sse.py` | Flux SSE en direct après rejeu, keepalive, format de trame. |
| `tests/test_export_journal.py` | Export JSON pour l'assistant : contenu complet, `--limit`, lecture seule, écriture atomique, base absente. |
| `tests/conftest.py`, `tests/broker_helpers.py` | Faux horloge, vérificateur, runner Ansible, réseau ; capture de logs. |

## Voir aussi

- [`../docs/contracts.md`](../docs/contracts.md) — événement d'anomalie, table de décision, logs, métriques
- [`../dashboard/README.md`](../dashboard/README.md) — consommation de `/stream`
- [`../infra/compose/docker-compose.yml`](../infra/compose/docker-compose.yml) — câblage réseau et docker-socket-proxy
- [`../ROADMAP.md`](../ROADMAP.md) — avancement
