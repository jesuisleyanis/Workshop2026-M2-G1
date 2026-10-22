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
| `auth_step_up_success` | auth | Ré-authentification réussie avant un gros virement (#51) — nouveau jeton à `auth_time` frais |
| `auth_step_up_failed` | auth | Mot de passe refusé à la ré-authentification (#51) — compté aussi dans `resilience_auth_logins_total{result="failed"}` (force brute visible) |
| `auth_identify_started` | auth | Étape 1 du back-office : identifiant saisi, caméra activée (consigne add. 1) |
| `auth_face_recognized` | auth | Étape 2 : visage reconnu, saisie du mot de passe débloquée |
| `auth_face_rejected` | auth | Étape 2 : visage non reconnu (identifiant vidé, caméra éteinte) |
| `auth_locked_out` | auth | Accès back-office bloqué (quota d'échecs atteint) |
| `led_state_published` | auth | État LED publié vers le broker MQTT |
| `led_publish_failed` | auth | Publication LED impossible (broker injoignable — fail-open) |
| `face_verify_match` | face-id | Vérification 1:1 : le visage correspond à l'identifiant |
| `face_verify_nomatch` | face-id | Vérification 1:1 : le visage ne correspond pas |
| `face_verify_error` | face-id | Traitement impossible : vérification impossible (gabarit d'un autre modèle, gabarit ou photos illisibles), erreur interne du modèle |
| `face_enrolled` | face-id | Enrôlement d'un visage (gabarits et vignettes stockés **chiffrés**, jamais l'image pleine résolution ni dans un log) |
| `face_enrollment_revoked` | face-id | Révocation d'un enrôlement (droit à l'effacement) |
| `auth_cooldown` | auth | Refroidissement actif après un refus (visage 30 s, mot de passe 3 s) |
| `admin_user_created` | auth | Back-office : création d'un compte par un administrateur |
| `admin_role_changed` | auth | Back-office : changement de rôle d'un compte |
| `admin_face_enrolled` | auth | Back-office : enrôlement du visage d'un compte par un administrateur |
| `admin_face_revoked` | auth | Back-office : révocation de l'enrôlement d'un compte par un administrateur |
| `backoffice_bootstrap` | auth | Création du premier administrateur du back-office au démarrage |
| `face_photos_viewed` | face-id | Consultation (par un administrateur) des photos d'enrôlement d'un compte |
| `face_enrollment_rejected` | face-id | Enrôlement refusé (pose manquante ou incorrecte, visages multiples, aucun visage) |
| `transaction_created` | payment-api | Virement fictif accepté |
| `transaction_rejected` | payment-api | Virement refusé (solde, validation) |
| `db_error` | payment-api, face-id | Erreur base de données (face-id : readiness KO, erreur SQL non gérée) |
| `beneficiary_added` | payment-api | Bénéficiaire enregistré (#43) — piste d'audit d'un ajout de compte mule après vol de session |
| `beneficiary_removed` | payment-api | Bénéficiaire supprimé (#43) |
| `card_frozen` | payment-api | Carte gelée par son titulaire (#47) — un seul événement par changement d'état |
| `card_unfrozen` | payment-api | Carte dégelée (#47) |
| `card_settings_changed` | payment-api | Réglages de carte modifiés (#47 : plafond, sans contact, paiement en ligne — noms des champs seulement) |
| `card_access_denied` | payment-api | Action sur une carte inconnue ou d'un tiers (#47, `404 card_not_found`) — une rafale = balayage d'ids (IDOR) |
| `scheduled_transfer_executed` | payment-api | Échéance d'un virement programmé exécutée par la tâche de fond (#48) |
| `scheduled_transfer_failed` | payment-api | Échéance refusée par le ledger (#48 : solde, plafond…, ou `internal_error` si la BDD tombe après réservation) — motif dans le message |
| `scheduled_transfer_created` | payment-api | Virement programmé créé (#48) — piste d'audit d'un virement permanent vers un compte mule |
| `scheduled_transfer_rejected` | payment-api | Création refusée (#48) — motif seul |
| `scheduled_transfer_changed` | payment-api | Programmation mise en pause, reprise ou annulée (#48) |
| `step_up_required` | payment-api | Virement (ou programmation) au-delà du seuil refusé faute de ré-authentification récente (#51, `403`) |
| `statement_exported` | payment-api | Relevé exporté (#50 : compte, période, nombre de lignes) — exfiltration de données = export massif |
| `transaction_access_denied` | payment-api | Lecture refusée d'une opération (#45 : id inconnu ou d'un tiers, message `unknown`/`foreign`) — une rafale = balayage d'ids (IDOR) |
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

### Vecteur de features consommé par le ML (fenêtre de 5 s, un vecteur par seconde)

Le `collector` interroge l'API Prometheus chaque seconde (`COLLECT_INTERVAL_SECONDS=1`, `rate(...[5s])`,
`PROM_RATE_WINDOW=5s` ; les services sont scrapés à 1 s) et construit ce vecteur ordonné. Le detector le reçoit dès
sa collecte (attente longue `GET /api/v1/features?after=<seq>&wait=5`) et confirme une anomalie sur 2 vecteurs
consécutifs au-dessus du seuil calibré, ou 1 seul au-dessus du seuil haut. Changer ces fenêtres impose de recapturer
et recalibrer le modèle. Ordre (voir `ml/shared/features.py` comme source de vérité) :

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
  },
  "source_ip": "192.168.137.42"
}
```

**`source_ip` (champ additif, optionnel)** : IP qui domine les logs d'accès du WAF (Loki, `client_ip`) sur les
30 dernières secondes, filtrés selon le type (flood : toutes les requêtes ; `auth_abuse` : logins en 401/429 ;
`web_attack` : 403). Renseignée par le detector seulement si elle pèse ≥ 60 % des lignes (et ≥ 5 lignes) ; absente
(`null`) sinon, et toujours pour `data_corruption` / `unknown`. Une seule IP littérale validée (jamais de nom ni de
réseau). Elle est la cible des actions `source: "from_event"` (`waf_block_ip`, `waf_blacklist_ip`) ; sans elle, ces
actions échouent proprement et l'action suivante de la règle s'exécute. Rétro-compatible : `schema_version` inchangée.

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

**`verify_first` (booléen optionnel, défaut `false`)** : `verify_tx` est joué AVANT toute action ; s'il passe,
l'attaque est contenue par les protections préventives (limitation de débit et ModSecurity du WAF) et
l'incident est clos sans action modifiante. Activé pour `service_flood` et `web_attack` (sinon : redémarrages
en boucle pendant un flood déjà écrêté — 12 en 20 min le 21/10 — et `web_attack` jamais clos). Jamais pour
`data_corruption` : une corruption ne se « contient » pas.

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

### 5.1 API `face-id` v2 (interne, réseau `app`, jamais sur `edge`)

Reconnaissance **1:1** (vérification identifiant ↔ visage) par **séquence de 3 poses** (`face`, `gauche`, `droite` — clés exactes). Modèle de l'équipe (`face_recognition`/dlib, 128-d, distance euclidienne, seuil **≤ 0,6**), backend `team`. Pose : `|rotation| ≤ 0,10` = face, `rotation ≥ 0,15` = gauche, `rotation ≤ −0,15` = droite. Détail : [ADR 0007](adr/0007-acces-hote-vivacite-poses-photos-chiffrees.md), [`services/face-id/README.md`](../services/face-id/README.md).

| Méthode & chemin | Auth | Description |
|---|---|---|
| `POST /api/v1/verify` | `X-Internal-Token` | `{username, frames:[{pose, image_b64}]×3}` (trois poses **distinctes**) → `{match: bool, model_version}`. Match ssi **chaque** frame montre la pose annoncée **et** une distance ≤ seuil vs le gabarit enrôlé de cette pose. Ni `score` ni motif d'échec dans la réponse (anti hill-climbing, anti-oracle) : le motif reste dans les logs. Utilisateur non enrôlé ≡ no-match. Appelé **uniquement par `auth`**. |
| `POST /api/v1/enroll` | `X-Internal-Token` | `{username, enrolled_by, poses:{face, gauche, droite}}` (images base64) → `200 {enrolled, model_version, poses}`. Une pose KO ⇒ **toute la série est refusée** : `422 {error:{code:"enrollment_rejected", details:[{pose, reason}]}}`, `reason ∈ no_face \| multiple_faces \| wrong_pose \| inconsistent \| missing \| invalid_image` ; `404 unknown_user`. |
| `GET /api/v1/enrollments/{username}/photos?viewer=<admin>` | `X-Internal-Token` | Vignettes JPEG (~240 px) **déchiffrées** `{photos:{pose: b64}}` pour l'administrateur ; journalise `face_photos_viewed` (qui a consulté les photos de qui). `404 not_enrolled`. |
| `DELETE /api/v1/enroll/{username}` | `X-Internal-Token` | `204`. Droit à l'effacement : suppression **complète** (gabarits + photos). |
| `GET /api/v1/enrollments` | `X-Internal-Token` | `[{username, enrolled_at, enrolled_by, model_version, poses, usable}]` — **aucune donnée biométrique**. `usable: bool` = la ligne est vérifiable par le modèle chargé (`model_version` égal au `model_version` courant du recognizer **et** vignettes chiffrées présentes, donc format v2). `false` (changement de modèle, ligne v1) ⇒ toute vérification échoue, **réenrôlement requis** ; `auth` ne compte alors **pas** la ligne comme un enrôlement. |
| `GET /health` · `GET /ready` · `GET /metrics` | — | `/ready` = modèle chargé + DB joignable. Le service **refuse de démarrer** si `FACE_DATA_KEY` est absente ou invalide. |

Les erreurs suivent le format des conventions d'API (`{error:{code, message}}`). Un enrôlement issu d'un autre modèle (`model_version` différent, ou ligne v1 non scellée) n'est pas comparable : la vérification journalise `face_verify_error` et le **réenrôlement** est requis.

### 5.2 API d'authentification à étapes (`auth`, consommée par le back-office)

Machine à états : `IDENTIFY → FACE → PASSWORD → OK` (détail, verrouillage et refroidissements : cadrage §5.1). **Ces routes (et §5.5) ne sont servies que par le listener hôte `127.0.0.1:9443` du WAF ; elles répondent 404 sur 80/443** (ADR 0007 ; seule `POST /api/v1/auth/step-up` du front, §6, reste publique).

| Méthode & chemin | Description |
|---|---|
| `POST /api/v1/auth/identify` | `{username}` → `200 {challenge_id, step:"face", expires_in, camera:true, poses:[3 poses]}`. `poses` est une **permutation aléatoire** (CSPRNG serveur) de `face`/`gauche`/`droite`, tirée à **chaque** `identify` et mémorisée dans le challenge (vivacité). `429` si bloqué (`locked_out`) ou en refroidissement (`cooldown`), toujours avec `Retry-After`. **Toujours 200** hors blocage/refroidissement (anti-énumération). Mode dégradé `BACKOFFICE_FACE_REQUIRED=false` : `step:"password"`, `poses:[]`, `camera:false`. |
| `POST /api/v1/auth/face` | `{challenge_id, frames:[{pose, image_b64}]×3}` → `200 {recognized, step:"password"\|"identify", attempts_left, cooldown}`. **L'ordre des frames doit être celui du challenge**, sinon échec (face-id n'est alors pas appelé). Plafond 800 000 car. base64 (~600 Ko) par frame. Non reconnu ⇒ `cooldown: 30`. `503 face_service_unavailable` si face-id est injoignable. |
| `POST /api/v1/auth/password` | `{challenge_id, password}` → `200 {access_token, token_type, expires_in, role}` (rôle privilégié) ; `401 invalid_credentials` + `Retry-After: 3` (refroidissement) ; `403 role_not_authorized` ; `409 wrong_step`. |
| `GET /api/v1/auth/device` | → `{led_online: bool \| null}` : dernier statut MQTT (LWT/heartbeat) du module LED ; `null` si inconnu, LED simulée, ou lien `auth`↔broker perdu/refusé (un `true` d'avant la coupure n'est jamais présenté comme courant). Sans authentification (booléen seul). |
| `POST /api/v1/login` | **Conservé** : comptes de service (`verify_tx`, `seed`) et front client. Hors facteur visage, **hors listener hôte** (sert sur 80/443). |

Identifiant du back-office **insensible à la casse** (`louis` atteint le compte `Louis`) : `identify` résout le nom canonique stocké (transmis à face-id et à l'étape mot de passe), verrouillage et journaux sont indexés sur le nom replié en minuscules, et la création/le bootstrap refusent un doublon de casse ; `POST /api/v1/login` reste sensible à la casse.

Verrouillage (consigne CA4) : quota d'échecs d'accès par `(username, source_ip)` — défaut **2** (« 1 reprise ») puis **5 min** (`BACKOFFICE_MAX_ATTEMPTS`, `BACKOFFICE_LOCKOUT_SECONDS`). Refroidissements **par poste** (`client_ip`), imposés côté serveur : visage refusé **30 s** (`BACKOFFICE_REJECT_COOLDOWN`), mot de passe refusé **3 s** (`BACKOFFICE_FAIL_COOLDOWN`) ; `identify` renvoie `429 cooldown` + `Retry-After` pendant ce délai (événement `auth_cooldown`). `challenge_id` à usage unique, TTL court (`BACKOFFICE_CHALLENGE_TTL`, défaut 60 s ; **120 s** dans le Compose : chargement à froid de MediaPipe + 3 maintiens de pose).

### 5.3 Protocole LED (MQTT)

Broker **Mosquitto** durci (`allow_anonymous false`, creds SOPS, **ACL par topic**, bind interface hotspot `MQTT_BIND_ADDR`, défaut `192.168.137.1` ; service Compose du profil `iot`, levé par `make up-iot`). `auth` publie des **états sémantiques** (`MqttLedNotifier`, QoS 1, `connect_async` + reconnexion automatique, publication non bloquante) ; le firmware ESP8266 rend les **motifs + timings**.

| Topic | Sens | Payload |
|---|---|---|
| `resilience/led/cmd` | hôte → ESP | `{"state":"idle\|recognized\|auth_ok\|auth_fail\|not_recognized","ts":"<iso8601>","challenge_id":"<uuid\|null>"}` |
| `resilience/led/status` | ESP → hôte | heartbeat (retained) + **LWT** `{"online": false}` ; **lu par `auth`** (ACL `read`) pour `GET /api/v1/auth/device` |

| État | Motif LED (rendu firmware) | Durée |
|---|---|---|
| `idle` | éteinte (défaut) | — |
| `recognized` | vert clignotant | jusqu'à l'état suivant |
| `auth_ok` | vert fixe | 30 s → éteinte |
| `auth_fail` | rouge clignotant ×10 (10 × 300 ms ≈ 3 s) | → éteinte |
| `not_recognized` | rouge fixe | 30 s → éteinte (la caméra du back-office est éteinte à la fin des 30 s) |

La publication MQTT est **fail-open** : un broker injoignable n'empêche jamais la connexion (événement `led_publish_failed`, métrique `resilience_led_publish_total{state,result}`). Sans `MQTT_HOST`, `auth` retombe sur un notifieur qui journalise seulement.

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

### 5.4 Modèle de données (`resilience_db`) et traitement des données biométriques

- `users.role` : `customer` (défaut) | `operator` | `admin`. Le back-office exige `operator`/`admin`.
- Table `face_enrollments` (migrations `0002` + `0009`) : `user_id` (FK `users.id`, **unique**), `embedding` (BYTEA — **blob chiffré** des 3 gabarits, un par pose), `photos` (BYTEA, nullable — **blob chiffré** des 3 vignettes JPEG ~240 px), `poses` (str, ex. `face,gauche,droite`), `model_version`, `enrolled_by`, `enrolled_at`. Les enrôlements v1 (non chiffrés, sans photos) sont **invalidés** : réenrôlement requis, détecté par `model_version`.
- **Chiffrement au repos** : AES-256-GCM, nonce 96 bits, format versionné `v1 | nonce | ciphertext+tag`, clé `FACE_DATA_KEY` (base64 de 32 octets, SOPS), **AAD = `username|templates` / `username|photos`** : un blob recopié sur une autre ligne ne se déchiffre pas. Seule la couche `face-id` détient la clé.
- **Amendement de la règle « jamais d'image stockée »** (versions antérieures du contrat et du cadrage §7) : le produit conserve désormais, pour chaque habilité, les **3 gabarits et 3 vignettes (≤ 240 px, jamais l'image pleine résolution), chiffrés**, afin de permettre l'affichage administrateur (`face_photos_viewed` journalisé) et le réenrôlement. Justification, limites et **validation attendue de l'équipe (Yanis)** : ADR 0007. Aucune image, aucun embedding, aucun mot de passe ni token ne figure dans un log.
- Perte de `FACE_DATA_KEY` ⇒ gabarits et photos **illisibles** : réenrôlement complet des agents (cf. `docs/pca-pra.md` §5.7). Droit à l'effacement : `DELETE /api/v1/enroll/{username}` (ou `DELETE /api/v1/admin/users/{u}/face`) supprime la ligne entière.

### 5.5 API d'administration et d'initialisation (`auth`, listener hôte uniquement)

Réservée au rôle `admin` (`Authorization: Bearer`, JWT émis par l'étape mot de passe ; le rôle est **revalidé en base** à chaque appel). Servie sur `127.0.0.1:9443` ; 404 sur 80/443.

| Méthode & chemin | Description |
|---|---|
| `GET /api/v1/admin/users` | `[{username, role, enrolled, stale, enrolled_at, enrolled_by}]` : `enrolled` = enrôlement **utilisable** (`usable` côté face-id) ; `stale` = ligne présente mais inutilisable (« Réenrôlement requis » dans le back-office) ; `enrolled_at`/`enrolled_by` renseignés dès qu'une ligne existe. |
| `POST /api/v1/admin/users` | `{username, password, role}` → `201 {username, role}` (compte du back-office, **sans compte bancaire**) ; `409 username_taken`. |
| `PATCH /api/v1/admin/users/{u}` | `{role}` → `200 {username, role}` ; `404 unknown_user` ; `409 last_admin`. |
| `PUT /api/v1/admin/users/{u}/face` | `{poses:{face, gauche, droite}}` → `200 {enrolled, model_version}` ; relai `enroll` avec `enrolled_by = sub` ; `422 enrollment_rejected` (+ `details` par pose). |
| `DELETE /api/v1/admin/users/{u}/face` | `204` ; `404 not_enrolled` ; `409 last_admin`. |
| `GET /api/v1/admin/users/{u}/face/photos` | `{photos:{pose: b64}}` ; consultation journalisée côté face-id (`face_photos_viewed`). |
| `GET /api/v1/auth/bootstrap` | `{required: bool}` — vrai seulement si `BACKOFFICE_BOOTSTRAP_TOKEN` est configuré **et** qu'aucun admin n'a d'enrôlement **utilisable** (des lignes périmées après un changement de modèle ne comptent pas). |
| `POST /api/v1/auth/bootstrap` | `{token, username, password, poses}` → `201 {username, role:"admin"}` : crée (ou met à jour un compte `operator`/`admin` existant) et enrôle le **premier administrateur**. Token comparé en temps constant, rate-limité (5/min), `403 bootstrap_denied` si non requis, token invalide, ou compte **client** existant (pas de promotion). Annulation propre si l'enrôlement échoue. |

**Garde-fou `last_admin`** : on ne peut ni rétrograder ni désenrôler le **dernier administrateur enrôlé** (sinon plus personne ne franchit l'étape visage). « Enrôlé » = enrôlement **utilisable** (`usable: true` chez face-id, contrat strict : une ligne sans le champ ne compte pas) ; un admin à l'enrôlement périmé se rétrograde ou se désenrôle librement. Événements : `admin_user_created`, `admin_role_changed`, `admin_face_enrolled`, `admin_face_revoked`, `backoffice_bootstrap` (table §1). Si face-id est injoignable, ces routes répondent `503 face_service_unavailable`.

### 5.6 Exposition réseau

| Point d'entrée | Contenu |
|---|---|
| WAF `443` (public ; `80` = `/healthz` + `301` vers HTTPS) | front client, API métier, `POST /api/v1/login`, `POST /api/v1/auth/step-up` (ré-authentification du front, #51, seule exception exacte) ; tout autre `/api/v1/auth/*` et `/api/v1/admin/*` → **404**. |
| WAF `127.0.0.1:9443` (**hôte uniquement**, jamais sur le hotspot) | back-office, `/api/v1/auth/*`, `/api/v1/admin/*`. Corps ≤ **4 MiB** (`client_max_body_size 4m` + plafonds ModSecurity relevés à 4 MiB dans ce seul bloc `server` : 3 captures JSON). Le serveur public 80/443 garde le défaut CRS de 128 KiB hors fichiers. |
| Mosquitto `${MQTT_BIND_ADDR:-192.168.137.1}:1883` (hotspot, profil `iot` : `make up-iot`) | bus LED uniquement (ACL §5.3). |

Seul un navigateur du PC Hôte joint l'étape visage : la caméra capturée est donc forcément celle de l'hôte (consigne).

---

## 6. API client `payment-api` (app bancaire, via le WAF)

Routes consommées par le front client (`services/front`). Toutes les réponses portent `Cache-Control: no-store` ; les ids de compte (corps et chemin) sont bornés à `[1, 2^31-1]` et les champs texte refusent les caractères de contrôle (`422`) — jamais un faux `503 db_error`. Le WAF route **chemin par chemin** : toute
nouvelle route exige sa `location` dans `security/waf/nginx.conf` (+ test). Bearer obligatoire sauf
mention contraire ; un objet d'autrui répond **404** (jamais 403 : pas d'oracle d'existence).
Montants en **centimes entiers**. Aucune nouvelle route n'ajoute de label de métrique : le label
`path` de §2 prend le gabarit de route, ce qui borne la cardinalité.

| Route | Auth | Contrat |
|---|---|---|
| `GET /api/v1/accounts` | JWT | `[{id, iban_fake, balance_cents, currency}]` |
| `POST /api/v1/transactions` | JWT | `{src_account, dst_account, amount_cents, category?}` → `201 TransactionOut` ; refus métier tracés (`transaction_rejected`). `category` ∈ `food, shopping, transport, subscriptions, health, leisure, housing, transfer, other`, **facultatif** (défaut `transfer` : `verify_tx` inchangé), invalide → `422 validation_error` (#44) |
| `GET /api/v1/transactions?limit=` | JWT | Historique de l'utilisateur, plus récent d'abord ; `category` et `request_id` = ceux de l'**émetteur**, `null` pour le destinataire (jamais divulgués) ; le **refus d'un tiers** vers moi n'apparaît pas (ni ici, ni par id, ni au relevé) |
| `GET /api/v1/transactions/{id}` | JWT | Détail d'une opération (#45) si le client possède le compte **source ou destination** ; sinon (ou id inconnu) `404 transaction_not_found` — jamais 403 (anti-énumération), tracé `transaction_access_denied`. Id hors `[1, 2^31-1]` → `422`. WAF : location regex dédiée, 60 req/min par IP, GET seul (le préfixe `/api/v1/transactions` reste sans limite : cible de `service_flood`). Même masquage de `category` que la liste |
| `GET /api/v1/cards` | JWT | Mes cartes (#47) `[{id, account_id, last4, holder, expiry_month, expiry_year, status: active\|frozen, payment_limit_cents, contactless, online_payments}]` — **jamais** de numéro complet ni de CVV (n'existent pas côté serveur) |
| `POST /api/v1/cards/{id}/freeze` · `/unfreeze` | JWT | `200` carte à jour, **idempotent** (un seul event `card_frozen`/`card_unfrozen` par changement réel). Carte d'autrui ou inconnue → `404 card_not_found`, tracé `card_access_denied`. Lecture-écriture sous verrou de ligne (gel concurrent) |
| `PATCH /api/v1/cards/{id}` | JWT | Corps partiel `{payment_limit_cents? ∈ [0, 1 000 000], contactless?, online_payments?}` (champ inconnu ou corps vide → `422`), carte gelée → `409 card_frozen`, event `card_settings_changed`. **Seule** route en `PATCH` : admis par `ALLOWED_METHODS` du CRS, refusé en `405` ailleurs (`$method_denied`). WAF : `/api/v1/cards` 60 req/min par IP |
| `GET /api/v1/scheduled-transfers` | JWT | Mes virements programmés (#48) `[{id, src_account, dst_account, amount_cents, category, frequency: once\|weekly\|monthly, start_on, next_run_on, end_on, status: active\|paused\|cancelled\|completed, last_run: {run_on, status: pending\|executed\|failed, error_code}\|null}]` |
| `POST /api/v1/scheduled-transfers` | JWT | `{src_account, dst_account, amount_cents, category?, frequency, start_on, end_on?}` → `201`. Refus : `404 account_not_found`/`destination_not_found`, `422 same_account`/`invalid_amount`/`amount_too_large`/`invalid_dates` (début ∈ [aujourd'hui UTC, +1 an], fin ≥ début), `409 schedule_limit` (20) |
| `PATCH /api/v1/scheduled-transfers/{id}` · `DELETE` | JWT | `{status: paused\|active}` → `200`, la reprise repart de la 1re échéance à venir (fermée → `409 schedule_closed`) ; `DELETE` → `204` (annulée, reste listée). D'autrui → `404 schedule_not_found`. **Exécution** par une tâche de fond de payment-api (`SCHEDULER_INTERVAL_S`, 60 s) via `ledger.transfer` (solde, plafond) ; idempotence par `UNIQUE(scheduled_id, run_on)` réservé avant le virement : **jamais deux exécutions**, même après un redémarrage par la remédiation ou avec plusieurs répliques |
| `GET /api/v1/notifications?unread=` | JWT | Notifications in-app (#49) `[{id, type, title, body, created_at, read_at}]`, 100 plus récentes. `type` ∈ `transfer_sent, transfer_received, transfer_rejected, limit_80, card_frozen, card_unfrozen, scheduled_executed, scheduled_failed` ; titres/corps en français (texte brut). Générées **dans la transaction** de l'événement (y compris l'avis de l'émetteur d'un virement programmé) ; virement interne, accepté ou refusé = aucune. Rétention 100/client appliquée hors chemin chaud (tâche de fond + lecture) |
| `GET /api/v1/notifications/unread-count` | JWT | `{count}` : badge de la cloche (sondé toutes les 30 s, un `COUNT`) |
| `POST /api/v1/notifications/{id}/read` · `/read-all` | JWT | Lecture idempotente (`200` notification) ; `read-all` → `{updated}` cloisonné à l'appelant. D'autrui → `404 notification_not_found`. WAF : 60 req/min par IP |
| `GET /api/v1/statements?account_id=&from=&to=&format=csv\|json` | JWT | Relevé (#50), bornes incluses (jours UTC). `csv` : `text/csv`, `Content-Disposition: attachment`, BOM, `;`, colonnes `Date;Référence;Libellé;Catégorie;Débit;Crédit;Statut` (montants non signés), **injection CSV neutralisée** (cellule commençant par `= + - @` tab/CR préfixée de `'`). `json` : `{account_id, iban_fake, holder, from, to, rows[], total_debit_cents, total_credit_cents}` (page imprimable). `404 account_not_found`, `422 invalid_period` (≤ 366 jours bornes incluses, dates 2000–2100), `422 statement_too_large` (> 5 000 lignes). Un refus d'un **tiers** n'apparaît jamais sur le relevé du destinataire. WAF : 10 req/min par IP. Event `statement_exported` |
| `POST /api/v1/auth/step-up` (service **auth**) | JWT | `{password}` → `200 {access_token, token_type, expires_in}` : même session (`sub`, `role`, **`exp` conservés** — jamais prolongée), claim `auth_time` frais (#51). `401 invalid_credentials` / `invalid_token`, `429 rate_limited` (**budget partagé** avec `/login`, même IP). Le login pose aussi `auth_time` |
| Step-up (`POST /transactions`, `POST /scheduled-transfers`, reprise `PATCH {status: active}`) | JWT | Montant > `STEP_UP_THRESHOLD_CENTS` (500 €) — sur un compte **plafonné**, montant + virements vers des tiers des 24 h (anti-fractionnement) — et `auth_time` absent ou âgé de plus de `STEP_UP_MAX_AGE_S` (300 s) → **`403 step_up_required`** (nouveau code d'erreur), rien n'est débité. `verify_tx` (1 €), le trafic normal (≤ 5 €) et `service_flood` (1 ct) restent sous le seuil |
| `GET /api/v1/limits` | JWT | Plafond mensuel par compte (#46) : `[{account_id, monthly_limit_cents, used_cents, remaining_cents, period_end}]`. `monthly_limit_cents: null` = **pas de plafond** (comptes de service `demo01`/`demo02` : `verify_tx`, trafic normal, `service_flood` ; comptes ouverts par `auth`). Fenêtre `[1er du mois, 1er suivant)` UTC, même filtre « dépense » que `/stats/spending`. Consommé = virements acceptés vers un autre client depuis le 1er du mois UTC ; `period_end` = date de remise à zéro. Au virement, dépassement → `409 limit_exceeded` (refus persisté, `transaction_rejected` + métrique `rejected`). WAF : 60 req/min par IP, GET seul |
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
