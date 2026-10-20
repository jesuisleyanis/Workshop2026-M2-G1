# Contrats d'interfaces — PROJECT RESILIENCE-ALPHA

> **Statut : FIGÉ en J1.** Toute modification se fait par PR + mise à jour de ce document et notification de l'équipe.
> C'est le document de référence qui permet aux 15 composants de s'intégrer sans friction. Chaque projet doit **respecter** ces contrats, pas les réinterpréter.

Ce document définit les quatre interfaces transverses que le sujet impose de maîtriser (§3.1 « interfaces avec les autres composants maîtrisées ») :

1. [Format de log JSON structuré](#1-format-de-log-json-structuré)
2. [Convention de nommage des métriques Prometheus](#2-métriques-prometheus)
3. [Schéma d'événement d'anomalie](#3-schéma-dévénement-danomalie)
4. [Table de décision incident → action](#4-table-de-décision-incident--action)
5. [Consigne Additionnelle 1 — authentification renforcée du back-office](#5-consigne-additionnelle-1--authentification-renforcée-du-back-office)

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

Machine à états : `IDENTIFY → FACE → PASSWORD → OK` (détail, verrouillage et refroidissements : cadrage §5.1). **Ces routes (et §5.5) ne sont servies que par le listener hôte `127.0.0.1:9443` du WAF ; elles répondent 404 sur 80/443** (ADR 0007).

| Méthode & chemin | Description |
|---|---|
| `POST /api/v1/auth/identify` | `{username}` → `200 {challenge_id, step:"face", expires_in, camera:true, poses:[3 poses]}`. `poses` est une **permutation aléatoire** (CSPRNG serveur) de `face`/`gauche`/`droite`, tirée à **chaque** `identify` et mémorisée dans le challenge (vivacité). `429` si bloqué (`locked_out`) ou en refroidissement (`cooldown`), toujours avec `Retry-After`. **Toujours 200** hors blocage/refroidissement (anti-énumération). Mode dégradé `BACKOFFICE_FACE_REQUIRED=false` : `step:"password"`, `poses:[]`, `camera:false`. |
| `POST /api/v1/auth/face` | `{challenge_id, frames:[{pose, image_b64}]×3}` → `200 {recognized, step:"password"\|"identify", attempts_left, cooldown}`. **L'ordre des frames doit être celui du challenge**, sinon échec (face-id n'est alors pas appelé). Plafond 800 000 car. base64 (~600 Ko) par frame. Non reconnu ⇒ `cooldown: 30`. `503 face_service_unavailable` si face-id est injoignable. |
| `POST /api/v1/auth/password` | `{challenge_id, password}` → `200 {access_token, token_type, expires_in, role}` (rôle privilégié) ; `401 invalid_credentials` + `Retry-After: 3` (refroidissement) ; `403 role_not_authorized` ; `409 wrong_step`. |
| `GET /api/v1/auth/device` | → `{led_online: bool \| null}` : dernier statut MQTT (LWT/heartbeat) du module LED ; `null` si inconnu, LED simulée, ou lien `auth`↔broker perdu/refusé (un `true` d'avant la coupure n'est jamais présenté comme courant). Sans authentification (booléen seul). |
| `POST /api/v1/login` | **Conservé** : comptes de service (`verify_tx`, `seed`) et front client. Hors facteur visage, **hors listener hôte** (sert sur 80/443). |

Verrouillage (consigne CA4) : quota d'échecs d'accès par `(username, source_ip)` — défaut **2** (« 1 reprise ») puis **5 min** (`BACKOFFICE_MAX_ATTEMPTS`, `BACKOFFICE_LOCKOUT_SECONDS`). Refroidissements **par poste** (`client_ip`), imposés côté serveur : visage refusé **30 s** (`BACKOFFICE_REJECT_COOLDOWN`), mot de passe refusé **3 s** (`BACKOFFICE_FAIL_COOLDOWN`) ; `identify` renvoie `429 cooldown` + `Retry-After` pendant ce délai (événement `auth_cooldown`). `challenge_id` à usage unique, TTL court (`BACKOFFICE_CHALLENGE_TTL`, défaut 60 s ; **120 s** dans le Compose : chargement à froid de MediaPipe + 3 maintiens de pose).

### 5.3 Protocole LED (MQTT)

Broker **Mosquitto** durci (`allow_anonymous false`, creds SOPS, **ACL par topic**, bind interface hotspot `MQTT_BIND`, défaut `192.168.137.1`). `auth` publie des **états sémantiques** (`MqttLedNotifier`, QoS 1, `connect_async` + reconnexion automatique, publication non bloquante) ; le firmware ESP8266 rend les **motifs + timings**.

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

### 5.4 Modèle de données (`resilience_db`) et traitement des données biométriques

- `users.role` : `customer` (défaut) | `operator` | `admin`. Le back-office exige `operator`/`admin`.
- Table `face_enrollments` (migration `0003`) : `user_id` (FK `users.id`, **unique**), `embedding` (BYTEA — **blob chiffré** des 3 gabarits, un par pose), `photos` (BYTEA, nullable — **blob chiffré** des 3 vignettes JPEG ~240 px), `poses` (str, ex. `face,gauche,droite`), `model_version`, `enrolled_by`, `enrolled_at`. Les enrôlements v1 (non chiffrés, sans photos) sont **invalidés** : réenrôlement requis, détecté par `model_version`.
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
| WAF `80`/`443` (public) | front client, API métier, `POST /api/v1/login` ; `/api/v1/auth/*` et `/api/v1/admin/*` → **404**. |
| WAF `127.0.0.1:9443` (**hôte uniquement**, jamais sur le hotspot) | back-office, `/api/v1/auth/*`, `/api/v1/admin/*`. Corps ≤ **4 MiB** (`client_max_body_size 4m`, plafonds ModSecurity `MODSEC_REQ_BODY_LIMIT` alignés : 3 captures JSON). |
| Mosquitto `${MQTT_BIND}:1883` (hotspot) | bus LED uniquement (ACL §5.3). |

Seul un navigateur du PC Hôte joint l'étape visage : la caméra capturée est donc forcément celle de l'hôte (consigne).

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
