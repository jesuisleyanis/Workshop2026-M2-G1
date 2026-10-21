# Contrats d'interfaces — PROJECT RESILIENCE-ALPHA

> **Statut : FIGÉ en J1.** Toute modification se fait par PR + mise à jour de ce document et notification de l'équipe.
> C'est le document de référence qui permet aux 15 composants de s'intégrer sans friction. Chaque projet doit **respecter** ces contrats, pas les réinterpréter.

Ce document définit les quatre interfaces transverses que le sujet impose de maîtriser (§3.1 « interfaces avec les autres composants maîtrisées ») :

1. [Format de log JSON structuré](#1-format-de-log-json-structuré)
2. [Convention de nommage des métriques Prometheus](#2-métriques-prometheus)
3. [Schéma d'événement d'anomalie](#3-schéma-dévénement-danomalie)
4. [Table de décision incident → action](#4-table-de-décision-incident--action)
5. [Consigne Additionnelle 1 — authentification renforcée du back-office](#5-consigne-additionnelle-1--authentification-renforcée-du-back-office)
6. [API client `payment-api` (app bancaire, via le WAF)](#6-api-client-payment-api-app-bancaire-via-le-waf)

Plus les conventions d'API REST et les codes de retour.

---

## 1. Format de log JSON structuré

Tous les services (payment-api, auth, remediation, detector, collector) émettent des logs **JSON sur une seule ligne** sur `stdout`. Promtail les récupère via le driver de logs Docker et les pousse dans Loki.

### Champs obligatoires

| Champ | Type | Description | Exemple |
|---|---|---|---|
| `ts` | string (ISO 8601 UTC) | Horodatage | `2026-10-21T09:14:33.482Z` |
| `level` | string | `DEBUG`\|`INFO`\|`WARNING`\|`ERROR`\|`CRITICAL` | `INFO` |
| `service` | string | Nom du service émetteur | `payment-api` |
| `event` | string | Identifiant d'événement en `snake_case` | `transaction_created` |
| `message` | string | Message humain | `Transaction 0x8f accepted` |
| `request_id` | string (uuid4) \| null | Corrèle une requête de bout en bout | `a1b2…` |

### Champs contextuels (selon l'événement)

| Champ | Quand | Description |
|---|---|---|
| `user` | requêtes authentifiées | Identifiant de l'utilisateur (jamais le mot de passe) |
| `client_ip` | requêtes HTTP entrantes | IP source (telle que vue derrière le WAF, via `X-Forwarded-For`) |
| `http_method` | requêtes HTTP | `GET`, `POST`… |
| `http_path` | requêtes HTTP | `/transactions` |
| `http_status` | réponses HTTP | `200`, `401`, `500` |
| `duration_ms` | réponses HTTP | Latence serveur en millisecondes |
| `anomaly_score` | detector uniquement | Score d'anomalie courant |
| `incident_id` | remediation uniquement | Corrèle les logs d'un même incident |

### Événements normalisés (`event`)

Ces noms sont **réservés** et alimentent les règles d'alerte Loki (fonction SOC) et les features ML. Ne pas en inventer d'autres sans mise à jour de ce contrat.

| `event` | Service | Signification |
|---|---|---|
| `auth_login_success` | auth | Connexion réussie |
| `auth_login_failed` | auth | Échec de connexion (mauvais identifiants) |
| `auth_rate_limited` | auth | Requête rejetée par le rate-limit |
| `auth_identify_started` | auth | Étape 1 du back-office : identifiant saisi, caméra activée (consigne add. 1) |
| `auth_face_recognized` | auth | Étape 2 : visage reconnu, saisie du mot de passe débloquée |
| `auth_face_rejected` | auth | Étape 2 : visage non reconnu (identifiant vidé, caméra éteinte) |
| `auth_locked_out` | auth | Accès back-office bloqué (quota d'échecs atteint) |
| `led_state_published` | auth | État LED publié vers le broker MQTT |
| `led_publish_failed` | auth | Publication LED impossible (broker injoignable — fail-open) |
| `face_verify_match` | face-id | Vérification 1:1 : le visage correspond à l'identifiant |
| `face_verify_nomatch` | face-id | Vérification 1:1 : le visage ne correspond pas |
| `face_verify_error` | face-id | Erreur de vérification (image illisible, aucun visage détecté) |
| `face_enrolled` | face-id | Enrôlement d'un visage (embedding stocké, jamais l'image) |
| `face_enrollment_revoked` | face-id | Révocation d'un enrôlement (droit à l'effacement) |
| `transaction_created` | payment-api | Virement fictif accepté |
| `transaction_rejected` | payment-api | Virement refusé (solde, validation) |
| `db_error` | payment-api | Erreur base de données |
| `beneficiary_added` | payment-api | Bénéficiaire enregistré (#43) — piste d'audit d'un ajout de compte mule après vol de session |
| `beneficiary_removed` | payment-api | Bénéficiaire supprimé (#43) |
| `beneficiary_rejected` | payment-api | Ajout refusé (IBAN inconnu, doublon, soi-même, quota) — une rafale = énumération d'IBAN |
| `waf_blocked` | waf (via log Nginx/ModSec) | Requête bloquée par le CRS |
| `anomaly_detected` | detector | Le score dépasse le seuil |
| `model_version_drift` | detector | Version scikit-learn chargée ≠ version d'entraînement du modèle |
| `remediation_started` | remediation | Début d'une action corrective |
| `remediation_action` | remediation | Action unitaire exécutée |
| `remediation_verified` | remediation | `verify_tx` repassé OK après action |
| `remediation_failed` | remediation | Échec / escalade |
| `assistant_index_built` | assistant | Index RAG (re)construit |
| `assistant_index_empty` | assistant | Aucune source trouvée : index RAG vide |
| `assistant_store_error` | assistant | Vector store (Chroma) non chargé / en erreur |
| `assistant_question_answered` | assistant | Réponse fournie à une question opérateur |
| `assistant_llm_unavailable` | assistant | Ollama injoignable — mode dégradé (lecture seule) |
| `assistant_http_request` | assistant | Trace d'une requête HTTP sortante de l'assistant |

### Exemple

```json
{"ts":"2026-10-21T09:14:33.482Z","level":"WARNING","service":"auth","event":"auth_login_failed","message":"Invalid credentials for user demo01","request_id":"a1b2c3d4-...","user":"demo01","client_ip":"192.168.137.50","http_method":"POST","http_path":"/login","http_status":401,"duration_ms":12}
```

> **Implémentation :** un module partagé `libs/logging` (Python) fournit `get_logger(service)` renvoyant un logger `structlog`/`logging` configuré avec ce format. Chaque service l'importe. Le middleware FastAPI injecte `request_id`, `client_ip`, `duration_ms`, `http_*` automatiquement.

---

## 2. Métriques Prometheus

Chaque service Python expose `/metrics` via `prometheus-fastapi-instrumentator`. Préfixe commun : `resilience_`.

### Métriques HTTP standard (auto-instrumentées)

| Métrique | Type | Labels | Source |
|---|---|---|---|
| `resilience_http_requests_total` | counter | `service`, `method`, `path`, `status` | tous |
| `resilience_http_request_duration_seconds` | histogram | `service`, `method`, `path` | tous |

### Métriques métier (exposées explicitement)

| Métrique | Type | Labels | Service | Alimente la feature |
|---|---|---|---|---|
| `resilience_transactions_total` | counter | `result` (`created`\|`rejected`) | payment-api | tx/min, taux d'échec |
| `resilience_auth_logins_total` | counter | `result` (`success`\|`failed`) | auth | échecs login/min |
| `resilience_auth_rate_limited_total` | counter | — | auth | abus auth |
| `resilience_db_errors_total` | counter | — | payment-api | erreurs DB |
| `resilience_waf_blocked_total` | counter | `rule` | waf-exporter | blocages WAF |
| `resilience_anomaly_score` | gauge | `service` | detector | **score ML temps réel** |
| `resilience_remediation_actions_total` | counter | `action`, `result` | remediation | — |
| `resilience_mttd_seconds` | gauge | `incident_id` | remediation | MTTD (détection → première action) |
| `resilience_mttr_seconds` | gauge | `incident_id` | remediation | MTTR |
| `resilience_face_verifications_total` | counter | `result` (`match`\|`nomatch`\|`error`) | face-id | vérifications 1:1 (consigne add. 1) |
| `resilience_face_verify_duration_seconds` | histogram | — | face-id | latence d'une vérification |
| `resilience_face_enrollments` | gauge | — | face-id | nombre de visages enrôlés |
| `resilience_auth_face_steps_total` | counter | `result` (`recognized`\|`rejected`) | auth | issues de l'étape visage |
| `resilience_auth_lockouts_total` | counter | — | auth | blocages d'accès back-office (5 min) |
| `resilience_led_publish_total` | counter | `state`, `result` (`ok`\|`error`) | auth | publications d'état LED |

Infrastructure complémentaire scrappée par Prometheus : **cAdvisor** (CPU/RAM par conteneur) et **postgres-exporter** (santé DB).

### Vecteur de features consommé par le ML (fenêtre de 15 s)

Le `collector` interroge l'API Prometheus et construit ce vecteur ordonné (voir `ml/shared/features.py` comme source de vérité) :

```
[ req_per_s, p95_latency_ms, ratio_4xx, ratio_5xx,
  auth_failed_per_s, waf_blocked_per_s,
  cpu_pct_max, mem_pct_max, db_errors_per_s ]
```

Définitions à noter (requêtes : `build_queries` de `ml/collector/collector.py`, partagées par la capture et la démo) :
- `auth_failed_per_s` = échecs de login (`resilience_auth_logins_total{result="failed"}`) **+ refus du rate-limit** (`resilience_auth_rate_limited_total`). Une force brute est vite refusée en 429 : sans le second terme, la feature retombe à ~0 pendant l'attaque.
- `cpu_pct_max`, `mem_pct_max` = conteneur le plus chargé **parmi les services de la plateforme** (`waf`, `front`, `payment-api`, `auth`, `postgres`), pas l'observabilité.

Changer une de ces définitions impose de recapturer la baseline et les attaques (`ml/training/README.md` §6).

> **Règle :** l'ordre et la liste des features sont figés dans `ml/shared/features.py`. Le `training` et le `detector` importent la même définition — jamais de duplication.

---

## 3. Schéma d'événement d'anomalie

Le `detector` émet cet objet JSON vers le moteur de remédiation (HTTP `POST /events`, authentifié — voir §API). **Chemin SOC (secondaire)** : Alertmanager poste son webhook natif (`{alerts:[…]}`) sur `POST /events/alertmanager` (même Bearer) ; l'adaptateur du moteur (`remediation/alertmanager.py`) le traduit en événement de ce schéma (`source: "alertmanager"`, `incident_type` = label de l'alerte, `anomaly_score`/`threshold` = 1.0, `event_id` stable par occurrence d'alerte). Les règles SOC Prometheus (`infra/prometheus/rules/soc.yml`) sont le miroir des règles Grafana.

```json
{
  "schema_version": "1.0",
  "event_id": "uuid4",
  "ts": "2026-10-21T09:14:35.000Z",
  "source": "detector",
  "service": "payment-api",
  "anomaly_score": 0.87,
  "threshold": 0.60,
  "incident_type": "service_flood",
  "features_top": [
    {"name": "req_per_s", "value": 420.0, "z": 9.2},
    {"name": "ratio_5xx", "value": 0.34, "z": 7.1}
  ],
  "evidence": {
    "prometheus_query": "rate(resilience_http_requests_total[1m])",
    "loki_query": "{service=\"payment-api\"} |= \"http_status\""
  }
}
```

### `incident_type` (énumération figée)

Ces valeurs font le **pont entre la détection et la table de décision**. Classées par règles sur les `features_top` (documenté comme limite assumée, cf. §3.3 du sujet).

| `incident_type` | Signal dominant | Action attendue (voir §4) |
|---|---|---|
| `service_flood` | `req_per_s`, `ratio_5xx`, `p95_latency` ↑ | blocage IP source + redémarrage du service |
| `auth_abuse` | `auth_failed_per_s` ↑ | blocage IP + durcissement rate-limit |
| `web_attack` | `waf_blocked_per_s` ↑ | confirmation blocage + blacklist source |
| `data_corruption` | `db_errors_per_s` ↑ + `verify_tx` KO | restauration dernier dump Postgres |
| `unknown` | anomalie sans signature claire | escalade + dry-run, pas d'action destructive |

> **Distinction imposée par le sujet (§2, §3.4) :** restauration de *disponibilité* (`service_flood`) ≠ correction d'une *compromission / corruption* (`data_corruption`). Ne jamais mapper l'un sur l'autre.

---

## 4. Table de décision incident → action

Source de vérité : `remediation/decision_table.yml`. Ce document en décrit le schéma ; le fichier YAML versionné fait foi.

```yaml
# remediation/decision_table.yml
version: "1.0"
defaults:
  cooldown_seconds: 60        # pas de ré-action sur le même incident avant ce délai
  max_attempts: 3             # tentatives avant escalade
  dry_run: false              # true en dev / mode répétition

rules:
  - incident_type: service_flood
    actions:
      - { type: waf_block_ip,     params: { source: "from_event" } }
      - { type: restart_service,  params: { service: "payment-api" } }
    verify: verify_tx
    escalation: notify_operator

  - incident_type: auth_abuse
    actions:
      - { type: waf_block_ip,       params: { source: "from_event" } }
      - { type: tighten_rate_limit, params: { service: "auth", factor: 0.5 } }
    verify: verify_tx
    escalation: notify_operator

  - incident_type: web_attack
    actions:
      - { type: confirm_waf_block, params: {} }
      - { type: waf_blacklist_ip,  params: { source: "from_event" } }
    verify: verify_tx
    escalation: notify_operator

  - incident_type: data_corruption
    actions:
      - { type: restore_pg_dump, params: { backup: "latest" } }
    verify: verify_tx
    escalation: notify_operator

  - incident_type: unknown
    actions:
      - { type: dry_run_report, params: {} }
    verify: verify_tx
    escalation: notify_operator
```

### Catalogue d'actions (implémentées dans `remediation/actions/`)

| `type` | Mécanisme | Privilège requis |
|---|---|---|
| `restart_service` | Docker API (via docker-socket-proxy, verbe limité) | restart conteneur |
| `recreate_service` | Docker API depuis image saine | create/remove conteneur |
| `waf_block_ip` / `waf_blacklist_ip` | Ansible → reload Nginx (fichier de deny) | écriture conf WAF + reload |
| `tighten_rate_limit` | appel API interne du service auth | aucun (API applicative) |
| `restore_pg_dump` | Ansible → `pg_restore` depuis backup planifié | accès réseau `data` |
| `confirm_waf_block` | lecture logs, pas d'action | aucun |
| `dry_run_report` | journalisation seule | aucun |
| `notify_operator` | webhook dashboard / log `remediation_failed` | aucun |

> **Sécurité (sujet §3.4, Axe 2) :** le moteur n'accède **jamais** au socket Docker brut. Il passe par un **docker-socket-proxy** n'autorisant que `POST /containers/{id}/restart` et les verbes strictement nécessaires. Son API `/events` est **authentifiée** (token partagé via SOPS) et **non exposée** sur le réseau `edge`. Voir `remediation/CAHIER-DES-CHARGES.md`.

---

## 5. Consigne Additionnelle 1 — authentification renforcée du back-office

> Cadrage complet : [`consigne-additionnelle-1.md`](consigne-additionnelle-1.md). Ces interfaces ne concernent que l'**accès privilégié** du back-office ; la boucle Zero-Touch Recovery (`verify_tx`, détection, remédiation) n'en dépend jamais.

### 5.1 API `face-id` (interne, réseau `app`, jamais sur `edge`)

Reconnaissance **1:1** (vérification identifiant ↔ visage). Stocke **l'embedding** (vecteur), **jamais l'image**.

| Méthode & chemin | Auth | Description |
|---|---|---|
| `POST /api/v1/verify` | `X-Internal-Token` (réseau interne) | `{username, image_b64}` → `{match: bool, model_version: str}`. Appelé **uniquement par `auth`**. Le `score` n'est **pas** renvoyé (anti hill-climbing) ; il reste dans les logs/métriques. |
| `POST /api/v1/enroll` | `X-Internal-Token` | `{username, images_b64: [...]}` → `{enrolled: bool, quality: float, model_version}`. |
| `DELETE /api/v1/enroll/{username}` | `X-Internal-Token` | `204`. Droit à l'effacement. |
| `GET /api/v1/enrollments` | `X-Internal-Token` | `[{username, enrolled_at, enrolled_by, model_version}]` — **aucune donnée biométrique**. |
| `GET /health` · `GET /ready` · `GET /metrics` | — | `/ready` = modèle chargé + DB joignable. |

### 5.2 API d'authentification à étapes (`auth`, consommée par le back-office)

Machine à états : `IDENTIFY → FACE → PASSWORD → OK` (détail et verrouillage : cadrage §5.1).

| Méthode & chemin | Description |
|---|---|
| `POST /api/v1/auth/identify` | `{username}` → `200 {challenge_id, step:"face", expires_in, camera:true}` ; `429 {retry_after}` si bloqué. **Toujours 200** hors blocage (anti-énumération). |
| `POST /api/v1/auth/face` | `{challenge_id, image_b64}` → `200 {recognized, step:"password"\|"identify", attempts_left}`. |
| `POST /api/v1/auth/password` | `{challenge_id, password}` → `200 {access_token, token_type, expires_in, role}` (rôle privilégié) ; `401 {step:"identify"}` sinon. |
| `POST /api/v1/login` | **Conservé** : comptes de service (`verify_tx`, `seed`) et front client. Hors facteur visage. |

Verrouillage (consigne CA4) : quota d'échecs d'accès par `(username, source_ip)` — défaut **2** tentatives (« 1 reprise ») puis **5 min** (`BACKOFFICE_MAX_ATTEMPTS`, `BACKOFFICE_LOCKOUT_SECONDS`). `challenge_id` à usage unique, TTL court (`BACKOFFICE_CHALLENGE_TTL`, défaut 60 s).

### 5.3 Protocole LED (MQTT)

Broker **Mosquitto** durci (`allow_anonymous false`, creds SOPS, **ACL par topic**, bind interface hotspot). `auth` publie des **états sémantiques** ; le firmware ESP8266 rend les **motifs + timings**.

| Topic | Sens | Payload |
|---|---|---|
| `resilience/led/cmd` | hôte → ESP | `{"state":"idle\|recognized\|auth_ok\|auth_fail\|not_recognized","ts":"<iso8601>","challenge_id":"<uuid\|null>"}` |
| `resilience/led/status` | ESP → hôte | heartbeat + **LWT** (disponibilité de l'objet) |

| État | Motif LED (rendu firmware) | Durée |
|---|---|---|
| `idle` | éteinte (défaut) | — |
| `recognized` | vert clignotant | jusqu'à l'état suivant |
| `auth_ok` | vert fixe | 30 s → éteinte |
| `auth_fail` | rouge clignotant ×10 | → éteinte |
| `not_recognized` | rouge fixe | 30 s → éteinte |

La publication MQTT est **fail-open** : un broker injoignable n'empêche jamais la connexion (événement `led_publish_failed`).

L'ESP8266 expose aussi trois commandes directes sur son adresse du PA. Elles exigent
HTTP Basic (`LED_HTTP_USERNAME`/`LED_HTTP_PASSWORD` dans le firmware), ne prennent pas
de corps et répondent `204` après déclenchement :

| Méthode et route | État appliqué |
|---|---|
| `POST /api/v1/led/green/blink` | `recognized` |
| `POST /api/v1/led/green/solid` | `auth_ok` |
| `POST /api/v1/led/red/blink` | `auth_fail` |

Ces commandes passent par la même machine à états que MQTT. Le service `auth` utilise
le contrat MQTT ; l'API HTTP est une commande directe de l'objet sur le réseau du PA.

### 5.4 Modèle de données (`resilience_db`)

- `users.role` : `customer` (défaut) | `operator` | `admin`. Le back-office exige `operator`/`admin`.
- Table `face_enrollments` : `user_id` (FK `users.id`, **unique**), `embedding` (BYTEA — **vecteur uniquement, jamais l'image**), `model_version` (str), `enrolled_by` (str), `enrolled_at` (timestamptz).

---

## 6. API client `payment-api` (app bancaire, via le WAF)

Routes consommées par le front client (`services/front`). Le WAF route **chemin par chemin** : toute
nouvelle route exige sa `location` dans `security/waf/nginx.conf` (+ test). Bearer obligatoire sauf
mention contraire ; un objet d'autrui répond **404** (jamais 403 : pas d'oracle d'existence).
Montants en **centimes entiers**. Aucune nouvelle route n'ajoute de label de métrique : le label
`path` de §2 prend le gabarit de route, ce qui borne la cardinalité.

| Route | Auth | Contrat |
|---|---|---|
| `GET /api/v1/accounts` | JWT | `[{id, iban_fake, balance_cents, currency}]` |
| `POST /api/v1/transactions` | JWT | `{src_account, dst_account, amount_cents, category?}` → `201 TransactionOut` ; refus métier tracés (`transaction_rejected`). `category` ∈ `food, shopping, transport, subscriptions, health, leisure, housing, transfer, other`, **facultatif** (défaut `transfer` : `verify_tx` inchangé), invalide → `422 validation_error` (#44) |
| `GET /api/v1/transactions?limit=` | JWT | Historique de l'utilisateur, plus récent d'abord ; `category` = celle choisie par l'**émetteur**, `null` pour le destinataire (jamais divulguée) |
| `GET /api/v1/transactions/{id}` | JWT | Détail d'une opération (#45) si le client possède le compte **source ou destination** ; sinon (ou id inconnu) `404 transaction_not_found` — jamais 403 (anti-énumération). Id hors `[1, 2^31-1]` → `422`. Même masquage de `category` que la liste |
| `GET /api/v1/stats/spending?period=week\|month&offset=0` | JWT | `offset` ∈ [-24, 0] (périodes passées). `{period, offset, start, end (exclusif), total_cents, by_category:[{category, amount_cents, share}], by_day:[{date, amount_cents}]}`. Dépense = virement **accepté** vers un compte **tiers** (refus et virements internes exclus). Semaine ISO / mois civil, jours **UTC**, agrégé en SQL (`GROUP BY`). WAF : 60 req/min par IP, GET seul. `category` n'est **pas** un label de métrique (§2 figé) (#44) |
| `GET /api/v1/beneficiaries` | JWT | Mes bénéficiaires `[{id, display_name, account_id, iban_fake, created_at}]`, triés par nom (#43) |
| `POST /api/v1/beneficiaries` | JWT | `{display_name (1–64), iban_fake}` → `201`. IBAN résolu vers un compte (espaces/casse ignorés, recherche exacte sur l'index unique). WAF : 30 req/min par IP (rafale 10) contre l'énumération ; events `beneficiary_added` / `beneficiary_rejected`. `404 account_not_found`, `409 beneficiary_exists`, `422 own_account`, `409 beneficiary_limit` (100) |
| `DELETE /api/v1/beneficiaries/{id}` | JWT | `204` (`beneficiary_removed`) ; bénéficiaire d'autrui ou inconnu → `404 beneficiary_not_found`. **Seule** route en `DELETE` : `ALLOWED_METHODS` du CRS l'admet, `nginx.conf` (`$method_denied`) le refuse en `405` sur tout autre chemin |
| `GET /api/v1/status` | **aucune** | `200 {"status":"ok","checked_at":"<iso Z>"}` / `503 {"status":"degraded",…}` si la BDD est injoignable. **Aucun détail interne** (ni version, ni hôte, ni exception). Cache serveur à vol unique `STATUS_CACHE_S` (2 s, borné 0,5–30 s) + `limit_req` WAF par IP (2 r/s, rafale 5), GET seul. **Exclue des métriques HTTP §2** comme `/ready` (sonde, pas trafic métier : n'altère pas les features ML). Un `200` ne prouve que l'accès BDD : le front confirme la reprise par une route métier (#42). |

---

## Conventions d'API REST

- **Auth (API métier) :** JWT Bearer (`Authorization: Bearer <token>`), signé HS256, clé via SOPS. Durée 15 min. Concerne `auth` et `payment-api`.
- **Auth (API interne du moteur de remédiation) :** **Bearer statique interne** — `Authorization: Bearer <REMEDIATION_TOKEN>` (token via SOPS). Ce service n'est **jamais exposé** sur `edge` ; il ne manipule pas d'identité utilisateur, donc un JWT serait superflu. Idem `INTERNAL_TOKEN` pour `auth` → `/internal/*`. Décision actée (ADR 0002).
- **Health :** chaque service expose `GET /health` (liveness, 200 si process up) et `GET /ready` (readiness, 200 si dépendances OK — DB joignable, etc.).
- **Erreurs :** corps JSON `{ "error": { "code": "string", "message": "string", "request_id": "..." } }`.
- **Codes retour scripts :** `verify_tx` et les scripts de démo renvoient `0` (succès) / `1` (échec) — contrat réutilisé par la boucle de remédiation et la CI future.
- **Versionnement :** préfixe `/api/v1` sur les routes métier.

---

## Qui consomme quoi (récapitulatif)

```
payment-api / auth ──logs JSON──► Promtail ──► Loki ──┐
                   ──métriques──► Prometheus ─────────┼──► collector ──features──► detector (ML)
cAdvisor / pg-exporter ─métriques► Prometheus ────────┘                              │
                                                                          événement d'anomalie (§3)
                                                                                     │
Prometheus rules SOC ─► Alertmanager ──webhook──► POST /events/alertmanager (adaptateur → §3) ─►│
                                                                                     ▼
                                                                          Moteur de remédiation
                                                                       (table de décision §4)
                                                                                     │
                                                                    actions ◄────────┤────► verify_tx
                                                                                     │
                                                                     SSE/WebSocket ──► Dashboard
```
