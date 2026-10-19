# Contrats d'interfaces — PROJECT RESILIENCE-ALPHA

> **Statut : FIGÉ en J1.** Toute modification se fait par PR + mise à jour de ce document et notification de l'équipe.
> C'est le document de référence qui permet aux 15 composants de s'intégrer sans friction. Chaque projet doit **respecter** ces contrats, pas les réinterpréter.

Ce document définit les quatre interfaces transverses que le sujet impose de maîtriser (§3.1 « interfaces avec les autres composants maîtrisées ») :

1. [Format de log JSON structuré](#1-format-de-log-json-structuré)
2. [Convention de nommage des métriques Prometheus](#2-métriques-prometheus)
3. [Schéma d'événement d'anomalie](#3-schéma-dévénement-danomalie)
4. [Table de décision incident → action](#4-table-de-décision-incident--action)

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
| `transaction_created` | payment-api | Virement fictif accepté |
| `transaction_rejected` | payment-api | Virement refusé (solde, validation) |
| `db_error` | payment-api | Erreur base de données |
| `waf_blocked` | waf (émis par le service `waf-exporter`, label Loki `service="waf-exporter"`) | Requête bloquée par le CRS |
| `http_request` | waf (access log Nginx) | Une requête reçue par le WAF. Écart assumé : `ts` au format Nginx `$time_iso8601` (secondes, `+00:00`), durée en `request_time_s` (secondes) — Nginx ne fournit ni millisecondes ISO ni durée en ms |
| `anomaly_detected` | detector | Le score dépasse le seuil |
| `remediation_started` | remediation | Début d'une action corrective |
| `remediation_action` | remediation | Action unitaire exécutée |
| `remediation_verified` | remediation | `verify_tx` repassé OK après action |
| `remediation_failed` | remediation | Échec / escalade |
| `assistant_index_built` | assistant | Index RAG (re)construit |
| `assistant_question_answered` | assistant | Réponse fournie à une question opérateur |
| `assistant_llm_unavailable` | assistant | Ollama injoignable — mode dégradé (lecture seule) |

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
| `resilience_mttd_seconds` | gauge | `incident_id` | remediation | MTTD |
| `resilience_mttr_seconds` | gauge | `incident_id` | remediation | MTTR |

Infrastructure complémentaire scrappée par Prometheus : **cAdvisor** (CPU/RAM par conteneur) et **postgres-exporter** (santé DB).

### Vecteur de features consommé par le ML (fenêtre de 15 s)

Le `collector` interroge l'API Prometheus et construit ce vecteur ordonné (voir `ml/shared/features.py` comme source de vérité) :

```
[ req_per_s, p95_latency_ms, ratio_4xx, ratio_5xx,
  auth_failed_per_s, waf_blocked_per_s,
  cpu_pct_max, mem_pct_max, db_errors_per_s ]
```

> **Règle :** l'ordre et la liste des features sont figés dans `ml/shared/features.py`. Le `training` et le `detector` importent la même définition — jamais de duplication.

---

## 3. Schéma d'événement d'anomalie

Le `detector` émet cet objet JSON vers le moteur de remédiation (HTTP `POST /events`, authentifié — voir §API). Alertmanager peut émettre un événement au même format.

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
    "loki_query": "{service=\"payment-api\"} |= \"db_error\""
  }
}
```

### `incident_type` (énumération figée)

Ces valeurs font le **pont entre la détection et la table de décision**. Classées par règles sur les `features_top` (documenté comme limite assumée, cf. §3.3 du sujet).

| `incident_type` | Signal dominant | Action attendue (voir §4) |
|---|---|---|
| `service_flood` | `req_per_s`, `ratio_5xx`, `p95_latency` ↑ | rate-limit + redémarrage + blocage IP source |
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

## Conventions d'API REST

- **Auth (API métier) :** JWT Bearer (`Authorization: Bearer <token>`), signé HS256, clé via SOPS. Durée 15 min. Concerne `auth` et `payment-api`.
- **Auth (API interne du moteur de remédiation) :** **Bearer statique interne** — `Authorization: Bearer <REMEDIATION_TOKEN>` (token via SOPS). Ce service n'est **jamais exposé** sur `edge` ; il ne manipule pas d'identité utilisateur, donc un JWT serait superflu. Idem `INTERNAL_TOKEN` pour `auth` → `/internal/*`. Décision actée (ADR 0002).
- **Health :** chaque service expose `GET /health` (liveness, 200 si process up) et `GET /ready` (readiness, 200 si dépendances OK — DB joignable, etc.).
- **Erreurs :** corps JSON `{ "error": { "code": "string", "message": "string", "request_id": "..." } }`.
- **Codes retour scripts :** `verify_tx` et les scripts de démo renvoient `0` (succès) / `1` (échec) — contrat réutilisé par la boucle de remédiation et la CI future.
- **`verify_tx` :** login `VERIFY_USER` → `GET /api/v1/accounts` (id source) → `POST /api/v1/transactions` `{src_account, dst_account, amount_cents}`, **ids entiers** (`TransactionIn`, `StrictInt`) → la transaction créée (`status: "created"`) figure dans `GET /api/v1/transactions`. Compte destinataire : `VERIFY_DST_ID`, sinon contrepartie d'une transaction déjà dans l'historique, sinon compte de `VERIFY_DST_USER` (second login). Cible : `BASE_URL` (WAF, défaut `https://localhost`).
- **Versionnement :** préfixe `/api/v1` sur les routes métier.

---

## Qui consomme quoi (récapitulatif)

```
payment-api / auth ──logs JSON──► Promtail ──► Loki ──┐
                   ──métriques──► Prometheus ─────────┼──► collector ──features──► detector (ML)
cAdvisor / pg-exporter ─métriques► Prometheus ────────┘                              │
                                                                          événement d'anomalie (§3)
                                                                                     │
Alertmanager ──alerte (schéma §3)──────────────────────────────────────────────────►│
                                                                                     ▼
                                                                          Moteur de remédiation
                                                                       (table de décision §4)
                                                                                     │
                                                                    actions ◄────────┤────► verify_tx
                                                                                     │
                                                                     SSE/WebSocket ──► Dashboard
```
