# Cahier des charges — Moteur de remédiation (`remediation/`)

> Quoi + pourquoi. Le « comment lancer / tester » est dans [`README.md`](README.md).
> Contrats d'interface : [`../docs/contracts.md`](../docs/contracts.md) (§1 logs, §2 métriques, §3 événement d'anomalie, §4 table de décision).
> Ce document décrit ce que le code **fait aujourd'hui** ; les écarts connus sont listés en §10.

## 1. Rôle

Le moteur de remédiation est l'automate de la **reprise autonome (Zero-Touch Recovery)**. Il :

1. **reçoit** un événement d'anomalie (`AnomalyEvent`, contrat §3) émis par le `detector` ML ou par Alertmanager ;
2. **décide** en lisant la table de décision `decision_table.yml` (contrat §4) : un `incident_type` → une séquence ordonnée d'actions ;
3. **agit** (blocage IP au WAF, redémarrage, durcissement du rate-limit, restauration d'un dump Postgres…) ;
4. **prouve le retour à la normale** en rejouant la transaction de contrôle `scripts/verify_tx` (exit 0 = OK, 1 = KO) ;
5. **clôt** l'incident (MTTD / MTTR) ou **escalade** après `max_attempts` ;
6. **raconte** tout cela en temps réel au dashboard (timeline SSE) et le **journalise** (SQLite local).

Aucune intervention humaine n'est dans la boucle : l'escalade (`notify_operator`) *signale* un échec, elle ne corrige rien.

Le moteur ne décide pas *de l'existence* d'une anomalie : la détection vient du modèle ML (contrat §3). Il ne contient **aucune règle de décision codée en dur** ; seulement des invariants de sécurité qui valident la table au chargement (§6).

## 2. Exigences du sujet couvertes

| Exigence | Intitulé | Comment le moteur la couvre |
|---|---|---|
| **R3** | Moteur de remédiation : reçoit l'incident, agit, suit le retour à l'état utilisable | `POST /events` → règle de la table → actions → boucle `verify_tx` → clôture (`closed`) ou escalade (`escalated`). Suivi visible : timeline SSE `detection → decision → action → verification → closure/escalation`, tables `incidents/actions/verifications/timeline`, métriques MTTD/MTTR. |
| **R15** | Moteur à privilèges maîtrisés (pas d'admin ouverte) | Voir §5 : pas de socket Docker brut (docker-socket-proxy + liste blanche côté client), API authentifiée fail-closed, jamais sur le réseau `edge`, playbooks Ansible nommés, services redémarrables en liste blanche, paramètres d'action issus de la table (jamais de l'événement), conteneur non-root. |

Exigences voisines servies : R2 (via `verify_tx`), R4/R20 (flux SSE pour la supervision et la démo), R6 (opérations WAF/PG via Ansible), R13 (token et secrets via SOPS/`*_FILE`), R14 (image durcie).

## 3. Interfaces

### 3.1 Consommées

| Interface | Détail | Référence |
|---|---|---|
| **Événement d'anomalie** | `POST /events`, corps = `AnomalyEvent` (`schema_version`, `event_id`, `ts`, `source`, `service`, `anomaly_score`, `threshold`, `incident_type`, `features_top[]`, `evidence`). Modèle `IncomingEvent` = `AnomalyEvent` (lib `resilience_common`) + **un champ optionnel additif `source_ip`** (une seule IP littérale, validée par `ipaddress`). Les champs inconnus sont ignorés (`extra="ignore"`). | `contracts.md` §3 |
| **Webhook Alertmanager** (chemin SOC, secondaire) | `POST /events/alertmanager`, corps = webhook Alertmanager v4 (`{alerts:[{status, labels, annotations, startsAt, fingerprint}]}`). Adaptateur `alertmanager.py` : alerte `firing` + label `incident_type` (énumération §3) → `IncomingEvent` (`source: alertmanager`, `service` = label ou défaut par type, score/seuil 1.0, `event_id` = uuid5(fingerprint, startsAt) ⇒ ré-émissions rejouées idempotemment, `source_ip` optionnelle, `evidence.prometheus_query` = annotation `expr`). Alertes résolues, sans `incident_type` ou hors énumération : ignorées (jamais mappées sur `unknown`). Même Bearer, mêmes garde-fous que `/events`. | `contracts.md` §3, `infra/prometheus/rules/soc.yml`, `infra/alertmanager/alertmanager.yml` |
| **Table de décision** | `decision_table.yml` (chemin : `DECISION_TABLE`), schéma `version / defaults / rules`. Validée au démarrage : table invalide → le service **refuse de démarrer**. Exposée en lecture par `GET /decision-table`. | `contracts.md` §4 |
| **`verify_tx`** | Script exécuté sans shell, avec timeout ; exit 0 = retour à la normale. | `contracts.md` « Codes retour scripts » |
| **docker-socket-proxy** | HTTP vers `DOCKER_PROXY_URL` (défaut `http://docker-socket-proxy:2375`). | §5 |
| **Ansible (ansible-runner)** | Playbooks nommés `waf_deny_ip.yml` et `pg_restore.yml` (`infra/ansible/playbooks/remediation/`, copiés dans `ANSIBLE_PROJECT_DIR`), exécutés **dans le conteneur** (`hosts: localhost`) ; artefacts dans `ANSIBLE_PRIVATE_DATA_DIR` (tmpfs). | §5.5, `infra/ansible/README.md` |
| **API interne du service `auth`** | `POST {AUTH_URL}/internal/tighten-rate-limit`, headers `X-Internal-Token` (= `INTERNAL_TOKEN`) et `Idempotency-Key` (= `incident_id`). | action `tighten_rate_limit` |
| **Loki** | `GET {LOKI_URL}/loki/api/v1/query_range`, lecture seule (action `confirm_waf_block`). | action `confirm_waf_block` |
| **Webhook opérateur** (optionnel) | `POST NOTIFY_WEBHOOK_URL` à l'escalade. | action `notify_operator` |

### 3.2 Exposées

Service FastAPI, port interne **8005**. Détail des endpoints dans le [`README.md`](README.md#endpoints).

| Endpoint | Auth | Rôle |
|---|---|---|
| `POST /events` | Bearer | Admission d'un `AnomalyEvent` → `202` `{incident_id, decision, dry_run, detail}` ; la remédiation tourne en tâche de fond. |
| `POST /events/alertmanager` | Bearer | Webhook Alertmanager → adaptateur → mêmes admissions que `/events` ; `202` `{accepted[], skipped[]}`. |
| `GET /incidents`, `GET /incidents/{id}` | Bearer | Journal des incidents (actions, vérifications, timeline). |
| `GET /decision-table` | Bearer | Table de décision chargée. |
| `GET /stream` | Bearer | Timeline temps réel en **SSE** (consommée par le dashboard). |
| `GET /health`, `GET /ready`, `GET /metrics` | aucune (réseaux internes uniquement) | Sondes et métriques Prometheus. |

Erreurs : corps `{"error": {"code", "message", "request_id"}}` (contrat « Conventions d'API REST ») ; header `X-Request-ID` propagé.

Logs JSON conformes au contrat §1 (événements `remediation_started`, `remediation_action`, `remediation_verified`, `remediation_failed`) et métriques conformes au contrat §2 : `resilience_remediation_actions_total{action,result}` (`result` ∈ `success|failure|dry_run`), `resilience_mttd_seconds{incident_id}`, `resilience_mttr_seconds{incident_id}`, `resilience_http_requests_total`, `resilience_http_request_duration_seconds`. Les gauges MTTD/MTTR sont bornées aux 20 derniers incidents (cardinalité).

## 4. Table de décision appliquée (contrat §4)

La sélection de règle est **exacte par type** (pas de repli implicite d'un type vers un autre). La table livrée (`version: "1.0"`) :

| `incident_type` | Actions (dans l'ordre) | Escalade |
|---|---|---|
| `service_flood` | `waf_block_ip(source=from_event)` → `restart_service(service=payment-api)` | `notify_operator` |
| `auth_abuse` | `waf_block_ip(source=from_event)` → `tighten_rate_limit(service=auth, factor=0.5)` | `notify_operator` |
| `web_attack` | `confirm_waf_block` → `waf_blacklist_ip(source=from_event)` | `notify_operator` |
| `data_corruption` | `restore_pg_dump(backup=latest)` | `notify_operator` |
| `unknown` | `dry_run_report` | `notify_operator` |

Chaque règle porte `verify: verify_tx` (seule valeur acceptée par le schéma). Les `params` viennent **uniquement de la table**, jamais de l'événement (l'événement ne fournit que l'IP source via `source: from_event`).

Catalogue d'actions (registre `actions.REGISTRY`) : `restart_service`, `recreate_service`, `waf_block_ip`, `waf_blacklist_ip`, `tighten_rate_limit`, `restore_pg_dump`, `confirm_waf_block`, `dry_run_report`, `notify_operator`. Trois actions sont **non mutantes** (`mutating = False` : `confirm_waf_block`, `dry_run_report`, `notify_operator`) ; les six autres sont mutantes (bloquées en dry-run, suivies d'une vérification).

## 5. Modèle de privilèges (R15 — point sondé par le jury)

Principe : le moteur est un composant **puissant par nature** (il redémarre des services, modifie le WAF, restaure une base). Il est donc contraint par couches successives pour qu'une compromission ou un bug du moteur n'offre pas une administration ouverte de l'hôte.

### 5.1 Pourquoi docker-socket-proxy et jamais le socket Docker brut

- Monter `/var/run/docker.sock` dans un conteneur revient à lui donner **root sur l'hôte** : l'API Docker permet de créer un conteneur privilégié avec `/` monté. Un moteur de remédiation compromis (ou simplement bogué) deviendrait un pivot total.
- Le moteur **ne monte jamais le socket** : l'image ne déclare aucun volume `docker.sock`, le service Compose ne le monte pas. Il parle **HTTP** à un `docker-socket-proxy` qui est le **seul** conteneur à monter le socket (en lecture seule).
- **Défense en profondeur côté client** (`actions/docker_proxy.py`) : même si le proxy était trop permissif, le client du moteur applique sa propre liste blanche `(méthode, chemin)` et lève `DockerProxyError` pour tout autre appel. Profil par défaut = **restart seul** :
  - `GET /_ping`, `GET /containers/json`, `GET /containers/{id}/json`, `POST /containers/{id}/restart`, `POST /containers/{id}/kill` **uniquement avec `signal=HUP`** (rechargement à chaud du WAF ; `KILL`/`TERM` refusés par le client *et* par le proxy).
- Le profil « recreate » (`stop`, `rename`, `create`, `start`, `DELETE`) n'est actif que si `DOCKER_PROXY_ALLOW_RECREATE=true` **et** que le proxy a été élargi en conséquence. Il est **désactivé par défaut** et `recreate_service` n'est référencé par aucune règle de la table livrée.
- `remediation/proxy/haproxy.cfg` fournit une configuration de proxy **stricte** (HAProxy) : seuls 5 couples méthode/chemin passent (`GET _ping`, `GET containers/json`, `GET containers/{id}/json`, `POST containers/{id}/restart`, `POST containers/{id}/kill?signal=HUP`), tout le reste renvoie 403. Elle documente pourquoi les variables `CONTAINERS=1 + POST=1` de `tecnativa/docker-socket-proxy` sont plus larges (elles ouvrent des *sections* entières de l'API, donc `POST /containers/create`). Voir §10 pour l'état de son câblage dans Compose.
- **Liste blanche de services** : `restart_service` / `recreate_service` n'agissent que sur `RESTARTABLE_SERVICES` (défaut `payment-api, auth, front`). Le moteur ne touche ni `postgres`, ni le proxy, ni lui-même, même si la table le demandait (`ActionError`).
- Le nom de service et l'image sont validés par regex ; les conteneurs sont résolus par label Compose `com.docker.compose.service`.

### 5.2 API authentifiée (`REMEDIATION_TOKEN`)

- Toutes les routes métier (`POST /events`, `GET /incidents`, `GET /incidents/{id}`, `GET /decision-table`, `GET /stream`) exigent `Authorization: Bearer <REMEDIATION_TOKEN>`.
- Comparaison à **temps constant** (`hmac.compare_digest`). Token en query string **refusé** (seul le header est lu).
- **Fail closed** : si `REMEDIATION_TOKEN` est absent ou plus court que 16 caractères, toutes les routes protégées répondent `503 auth_not_configured` ; `/ready` passe à 503 ; une erreur est loguée au démarrage. Il n'y a **aucune valeur par défaut** pour les secrets.
- Échec d'authentification : `401 unauthorized` + `WWW-Authenticate: Bearer`, et log `warning` (request_id, IP cliente, méthode, chemin) — sans jamais journaliser le token.
- Le token est destiné à être fourni via SOPS + age : variable `REMEDIATION_TOKEN` ou, de préférence, fichier `REMEDIATION_TOKEN_FILE` monté en lecture seule (le fichier est prioritaire). Idem pour `INTERNAL_TOKEN`. Rien en clair dans l'image ni dans git.
- Seules les sondes `/health`, `/ready`, `/metrics` sont sans authentification ; elles ne sont joignables que depuis les réseaux internes. `/docs`, `/redoc` et `/openapi.json` sont désactivés (pas de schéma exposé inutilement).

### 5.3 Jamais exposé sur le réseau `edge`

- Le service est rattaché au **seul réseau `app`** (interne) et n'a **aucun `ports:`**. Seul le WAF est exposé (80/443). Le conteneur écoute sur `0.0.0.0:8005` *à l'intérieur de son namespace réseau* (nécessaire aux autres services du réseau `app`) ; l'exposition réelle est décidée par Compose, pas par le code.
- Le navigateur ne parle jamais directement au moteur : le dashboard le joint via un reverse-proxy nginx qui n'expose que `GET /remediation/stream` (lecture seule) et injecte lui-même l'en-tête `Authorization` (`REMEDIATION_AUTH_HEADER`). Le token n'est donc jamais embarqué dans le bundle front.

### 5.4 Durcissement du conteneur

Image `python:3.12-slim` multi-stage (aucun outil de build dans l'image finale), utilisateur **non-root** (uid/gid 10001, shell `nologin`), code et table en lecture seule (propriété root), **seul point inscriptible** : le volume `/var/lib/remediation` (journal SQLite), `HEALTHCHECK` sans `curl`, `--no-server-header`, `Dockerfile.dockerignore` excluant `.env*`, `*.enc.*`, clés age et tests. Le durcissement runtime (`cap_drop: ALL`, `read_only`, limites CPU/RAM) est porté par Compose.

### 5.5 Autres bornes de privilège

- **Ansible** : seuls les playbooks `waf_deny_ip.yml` et `pg_restore.yml` (`ALLOWED_PLAYBOOKS`) peuvent être lancés ; ni le nom du playbook ni ses variables ne viennent de l'événement (autre playbook → refus, `rc=-1`). Ils s'exécutent **dans le conteneur du moteur** (`hosts: localhost`), jamais sur l'hôte ni via `docker exec` : le moteur n'obtient que les accès strictement nécessaires (volume `waf-deny` partagé avec le WAF, réseau `data` + client Postgres pour la restauration, dumps en lecture seule).
- **Blocage IP** : l'IP vient de `source_ip` (validée comme IP littérale unique : ni réseau, ni nom, ni texte libre, car elle finit dans une configuration Nginx). Refus de bloquer `NEVER_BLOCK_IPS` (défaut : `127.0.0.1`, `::1`, `192.168.137.1`, l'hôte du réseau `RESILIENCE-G1`), ni boucle locale / non spécifiée / multicast.
- **Restauration** : `backup` = `latest` ou un nom simple (regex, pas de `/`, pas de `..` : pas de path traversal).
- **`verify_tx`** : lancé sans shell (`create_subprocess_exec`), groupe de processus dédié, timeout qui tue aussi les enfants.
- **Sérialisation** : un verrou (`_action_lock`) interdit deux actions mutantes simultanées.
- **Messages d'erreur** : les erreurs inattendues sont réduites au nom du type d'exception dans le journal (pas de fuite de détails internes).
- **Périmètre** : toutes les actions visent le SI du projet (réseau `RESILIENCE-G1`) ; aucune action offensive.

## 6. Garde-fous implémentés

Valeurs par défaut (`decision_table.yml`, section `defaults`) : `cooldown_seconds: 60`, `max_attempts: 3`, `dry_run: false`. Bornes validées : `cooldown_seconds ≥ 0`, `1 ≤ max_attempts ≤ 10`.

| Garde-fou | Comportement réel |
|---|---|
| **Dédoublonnage par clé** | Clé d'incident = `incident_type:service`. Un événement pour une clé déjà en cours est ignoré (`decision: "duplicate"`, trace `skipped` dans la timeline). |
| **Idempotence sur `event_id`** | Un `event_id` déjà vu renvoie l'incident existant (`decision: "replayed"`), sans nouvelle remédiation (le detector peut rejouer sur timeout réseau). Index unique SQLite sur `event_id`. |
| **Cooldown (admission)** | Si la dernière action sur la même clé date de moins de `cooldown_seconds`, le nouvel événement est refusé (`decision: "cooldown"`, trace `skipped` dans la timeline de l'incident précédent). Le cooldown est **par clé** : un autre type ou un autre service n'est pas bloqué. |
| **Cooldown (entre tentatives)** | Avant la tentative N > 1, le moteur attend que `cooldown_seconds` se soit écoulé depuis la dernière action. |
| **`max_attempts`** | Une tentative = toute la séquence d'actions de la règle (avec vérification après chaque action mutante réussie et après la dernière). Séquence épuisée sans `verify_tx` OK = 1 tentative consommée. À `max_attempts`, **escalade** : exécution de l'action `escalation` (`notify_operator`), log `remediation_failed`, incident `escalated`. |
| **Vérification après action** | Après toute action mutante réussie (et après la dernière action réussie), `verify_tx` est rejoué jusqu'à `VERIFY_RETRIES` fois (défaut 5, intervalle `VERIFY_INTERVAL_S` = 3 s). Vérif OK → les actions suivantes de la règle sont **sautées** et l'incident est clos ; KO → action suivante. Une action en échec ne bloque pas la suivante (mais ne déclenche pas de vérification). |
| **`dry_run`** | Actif si `REMEDIATION_DRY_RUN` **ou** `defaults.dry_run` : l'environnement peut seulement **forcer** le dry-run, jamais le désactiver. En dry-run, les actions mutantes ne sont **pas exécutées** (seul `plan()` est journalisé, résultat `dry_run`), les actions non mutantes (lecture seule) s'exécutent, aucune vérification n'est faite, l'incident se termine en statut `dry_run`. L'escalade `notify_operator` reste exécutée (elle ne modifie pas le SI). |
| **Timeout d'action** | `ACTION_TIMEOUT_S` (défaut 300 s) ; dépassement = action en échec. |
| **Arrêt / redémarrage** | À l'arrêt, les tâches en cours sont annulées et marquées `interrupted`. Au démarrage, tout incident resté `in_progress` est marqué `interrupted` (log `warning`). |
| **Erreur interne** | Toute exception non prévue dans le déroulé escalade l'incident (pas d'incident sans issue). |
| **Validation de la table** | Au chargement (`decision.py`) : action inconnue, paramètres invalides, type d'incident sans règle ou en double, escalade inconnue ou mutante, clés YAML inconnues → `DecisionTableError`, le service ne démarre pas. |

### Garde-fou « unknown »

L'invariant de validation interdit toute action mutante dans la règle `unknown` : un signal non classé n'entraîne qu'un rapport (`dry_run_report`), puis la boucle de vérification et, au besoin, l'escalade. Aucune action destructive.

## 7. Distinction `service_flood` (disponibilité) vs `data_corruption` (correction)

Le sujet (§2, §3.4) impose de ne pas confondre **restaurer la disponibilité** et **corriger une compromission / corruption**. Le moteur matérialise cette distinction à trois niveaux :

1. **Dans la table** : `service_flood` = couper la source (`waf_block_ip`) puis redémarrer (`restart_service`) ; `data_corruption` = `restore_pg_dump` seul, du dernier dump valide.
2. **Dans le code (invariants de `decision.py`)**, vérifiés au chargement, donc un YAML édité par erreur ne peut pas les violer :
   - `data_corruption` **doit** contenir `restore_pg_dump` et **ne doit pas** contenir `restart_service` / `recreate_service` ;
   - `restore_pg_dump` est **réservé** à `data_corruption` (interdit dans toute autre règle, donc jamais dans `service_flood`) ;
   - sélection de règle exacte par type, sans repli.
3. **Dans les privilèges** : `restore_pg_dump` passe par le playbook Ansible `pg_restore.yml` (exécuté dans le conteneur, `pg_restore` direct sur le réseau `data`), `restart_service` par le docker-socket-proxy ; ce sont deux canaux distincts.

Pourquoi : redémarrer un service après une corruption de données **ne corrige rien** (les données corrompues survivent au redémarrage) et masquerait l'incident ; à l'inverse, restaurer une base pour un simple pic de charge détruirait des données saines. Les tests couvrent les deux sens (`test_decision_table.py`, `test_engine.py`).

## 8. Journal et observabilité de l'incident

- **Journal SQLite** (`INCIDENTS_DB`, volume dédié) : tables `incidents` (statut, tentatives, `detected_at`, `first_action_at`, `closed_at`, `mttd_seconds`, `mttr_seconds`, `reason`), `actions`, `verifications`, `timeline`. Statuts finaux : `closed`, `escalated`, `dry_run`, `interrupted`.
- **MTTD** = détection (`ts` de l'événement) → première action. **MTTR** = détection → vérification OK.
- **Timeline** (diffusée par `GET /stream`) : phases `detection → decision → action → verification → closure | escalation`, statuts `info | running | ok | ko | failed | skipped | dry_run`.

## 9. Critères d'acceptation

| # | Critère | Vérifié par |
|---|---|---|
| A1 | Le moteur démarre avec la table livrée ; une table invalide (action inconnue, type manquant, doublon, clé inconnue, paramètre dangereux) l'empêche de démarrer. | `tests/test_decision_table.py` |
| A2 | Pour chacun des 5 `incident_type`, la séquence d'actions exécutée est celle de la table, avec les paramètres de la table. | `test_decision_table.py`, `test_engine.py` |
| A3 | `service_flood` ne restaure jamais de dump ; `data_corruption` ne redémarre/recrée jamais de service ; `restore_pg_dump` refusé hors `data_corruption` ; `unknown` sans action destructive. | `test_decision_table.py`, `test_engine.py` |
| A4b | Règle `verify_first` (flood, web_attack) : `verify_tx` joué avant toute action ; OK = attaque contenue par le WAF, incident clos sans action (pas de redémarrage en boucle). | `test_engine.py` |
| A4 | `verify_tx` OK clôt l'incident et calcule MTTD/MTTR ; KO passe à l'action suivante ; OK après la 1re action saute les suivantes ; la vérification est retentée tant que la plateforme n'est pas saine. | `test_engine.py` |
| A5 | Cooldown : pas de ré-action sur la même clé avant `cooldown_seconds`, et le cooldown est par clé. | `test_engine.py` |
| A6 | `max_attempts` atteint ou toutes actions en échec → escalade (`notify_operator`, log `remediation_failed`). | `test_engine.py` |
| A7 | Dédoublonnage : événement dupliqué en cours ignoré ; `event_id` rejoué idempotent. | `test_engine.py` |
| A8 | `dry_run` n'exécute aucune action mutante, ne peut pas être désactivé par la table lorsqu'il est forcé par l'environnement, laisse passer les actions en lecture seule. | `test_engine.py` |
| A9 | Pas d'IP protégée ou absente bloquée ; service hors liste blanche non redémarré. | `test_engine.py` |
| A10 | Le client Docker n'émet que les verbes du profil restart par défaut ; `recreate` refusé sans profil élargi ; rollback si la recréation échoue. | `test_actions.py` |
| A11 | Playbook non listé refusé ; paramètres dangereux rejetés ; contrat de sortie de `verify_tx` respecté. | `test_actions.py` |
| A12 | Toute route métier sans token ou avec mauvais token → 401 ; token en query refusé ; sans `REMEDIATION_TOKEN` configuré → fail closed (503). | `test_api.py` |
| A13 | `/ready` passe à 503 si le docker-socket-proxy est injoignable ; `/health` et `/ready` sans authentification. | `test_api.py` |
| A14 | La timeline SSE rejoue l'historique, supporte `Last-Event-ID`, diffuse en temps réel et envoie un keepalive. | `test_api.py`, `test_sse.py` |
| A15 | Logs et métriques conformes aux contrats §1 et §2. | `test_engine.py`, `test_api.py` |
| A16 | Image non-root, sans accès au socket Docker, service sans `ports:` et absent du réseau `edge`. | revue de `Dockerfile` et de `infra/compose` (pas de test automatisé) |
| A17 | **Démo** : sur injection d'un `service_flood` puis d'un `data_corruption`, retour à la normale constaté par `verify_tx` **sans intervention humaine**. | `tests/e2e/` / `make demo` (hors périmètre de ce dossier) |

## 10. Limites et écarts connus (constatés dans le dépôt)

Écarts **résolus** (J3, tickets #3, #8 et #13 — chemin SOC `POST /events/alertmanager` câblé et authentifié, I6 fermé) : le proxy strict `proxy/haproxy.cfg` est celui câblé dans Compose (I1) ; `verify_tx` et les playbooks sont embarqués dans l'image et exécutés dans le conteneur (plus de `docker exec`, variables `deny_ip`/`deny_list`/`backup`/`incident_id` alignées, inventaire portable) ; la double déclaration des métriques HTTP qui faisait crasher le boot est supprimée.

Écarts restants :

- **Validation live** : le plan d'exécution (SIGHUP du WAF via le proxy, `pg_restore` sur le réseau `data`) est testé unitairement et par exécution réelle du playbook WAF, mais la boucle complète KO → action → OK reste à rejouer stack levée (`tests/e2e`).
- **Dump sain** : `restore_pg_dump` suppose un dump produit au préalable par `playbooks/pg_backup.yml` (opérateur, côté hôte) ; pas encore de job de sauvegarde planifié.
- **Champ `source_ip`** : extension additive du contrat §3 (absente du schéma contractuel), à émettre par le detector (ou en label `source_ip` d'une alerte SOC) pour que `source: from_event` fonctionne ; sans lui, `waf_block_ip` / `waf_blacklist_ip` échouent proprement (« aucune IP source »). Les règles SOC Prometheus livrées n'ont pas d'IP source (agrégats) : par le chemin SOC, les actions de blocage IP échouent proprement et la règle poursuit (restart / rate-limit / restore).
- **Authentification** : bearer statique partagé (`REMEDIATION_TOKEN`), et non le JWT HS256 décrit dans « Conventions d'API REST » ; pas de préfixe `/api/v1` sur les routes. Choix volontaire pour une API service-à-service interne.
- **Idempotence de `tighten_rate_limit`** : repose sur le service `auth`, qui doit dédoublonner sur `Idempotency-Key`.
- **`GET /stream`** est protégé par le Bearer ; un `EventSource` navigateur ne pouvant pas poser de header, le dashboard passe par son reverse-proxy nginx qui l'injecte.
- **Journal** : SQLite local mono-processus (un seul écrivain) ; pas de haute disponibilité du moteur.
- **Tests** : `recreate_service` est implémenté et testé mais volontairement hors de la table livrée ; l'intégration Ansible réelle est couverte pour `waf_deny_ip.yml` (ansible-runner sur fichier temporaire), `pg_restore.yml` n'est validé que par `--syntax-check` hors stack.
