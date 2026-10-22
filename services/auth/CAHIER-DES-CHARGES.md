# Cahier des charges — `services/auth`

## 1. Rôle

Service d'**authentification** de la plateforme de paiement fictive : crée des comptes, vérifie les identifiants et délivre des **JWT** consommés par `payment-api`. C'est aussi la **cible naturelle du scénario `auth_abuse`** (brute-force / credential stuffing) : il porte le rate-limit, produit les signaux de détection (`auth_failed_per_s`) et expose un point d'entrée interne permettant à la remédiation de **durcir la limite à chaud** (`tighten_rate_limit`).

Il porte aussi l'**accès privilégié du back-office** (consigne additionnelle 1) : authentification **à étapes** identifiant → visage (3 poses aléatoires, via le service `face-id`) → mot de passe, pilotage d'une **LED** (MQTT), et **API d'administration des habilitations** (comptes, rôles, enrôlement/révocation du visage) avec **bootstrap** du premier administrateur. La boucle Zero-Touch Recovery (`verify_tx`, `/login`) n'en dépend jamais.

- Port interne **8002**, réseau Docker **`app`** (+ `data` pour joindre PostgreSQL). Nom de service Compose : **`auth`**. Jamais exposé directement : seul le WAF l'est.

## 2. Exigences du sujet couvertes

| Réf. | Exigence | Comment |
|---|---|---|
| **R1** | SI de paiement fictif : auth, BDD, microservices conteneurisés | Service FastAPI conteneurisé, persistance PostgreSQL partagée (`libs/python/resilience_db`) |
| **R2** | (indirect) transaction traçable | Fournit l'identité (`sub`) et les comptes ; la traçabilité des virements est dans `payment-api` |
| **R7/R12** | Observabilité / fonction SOC | Logs JSON contrat §1 (`auth_login_*`, `auth_rate_limited`) + métriques §2 → règles Loki/Prometheus |
| **R8** | Détection ML | Alimente la feature `auth_failed_per_s` (via `resilience_auth_logins_total{result="failed"}`) |
| **R14/R15** | Durcissement / privilèges maîtrisés | Image non-root/slim/healthcheck, API interne protégée par token, comparaison en temps constant ; accès back-office à 3 facteurs (identifiant, visage, mot de passe), rôles `customer`/`operator`/`admin`, garde « dernier admin enrôlé » |

## 3. Interfaces

### Exposées (détail des formats : [`docs/contracts.md`](../../docs/contracts.md))

| Méthode & chemin | Auth | Description |
|---|---|---|
| `POST /api/v1/register` | — | `{username, password}` → `201 {id, username}` ; crée aussi un compte `EUR` à solde **0** (jamais de création de monnaie). `409 username_taken` |
| `POST /api/v1/login` | — (rate-limité) | `{username, password}` → `200 {access_token, token_type:"bearer", expires_in:900}` (JWT avec `auth_time`, #51) ; `401 invalid_credentials` ; `429 rate_limited` + `Retry-After` |
| `POST /api/v1/auth/step-up` | JWT + même quota que `/login` | `{password}` → `200` même session (`exp` et `role` conservés, jamais prolongée) à `auth_time` frais (#51) ; `401 invalid_credentials` / `invalid_token` ; `429` (budget **partagé** avec `/login`) ; events `auth_step_up_success` / `auth_step_up_failed`, échecs comptés dans `resilience_auth_logins_total{failed}` |
| `GET /health` | — | Liveness (process up) |
| `GET /ready` | — | Readiness : `200` si la DB répond (`SELECT 1`), sinon `503 db_unavailable` |
| `GET /metrics` | — (réseau interne) | Prometheus |
| `POST /internal/tighten-rate-limit` | header `X-Internal-Token` | `{factor ∈ ]0,1]}` → limite × factor (plancher 1/période) ; renvoie `{previous_limit,current_limit}`. Action `tighten_rate_limit` de la table de décision (§4) |
| `POST /internal/reset-rate-limit` | header `X-Internal-Token` | Restaure la limite de référence (retour à la normale après incident / entre deux démos) |
| `POST /api/v1/auth/identify` | — (rate-limité `BACKOFFICE_RATE_LIMIT`) | `{username}` → `200 {challenge_id, step, expires_in, camera, poses}` ; `poses` = ordre aléatoire des 3 poses (`face`,`gauche`,`droite`) à présenter. **Toujours 200** hors blocage (anti-énumération) ; `429 locked_out` / `429 cooldown` + `Retry-After` |
| `POST /api/v1/auth/face` | — (rate-limité) | `{challenge_id, frames:[{pose, image_b64}×3]}` (ordre des poses = celui d'`identify`) → `200 {recognized, step:"password"\|"identify", attempts_left, cooldown}` ; refus = cooldown **30 s** ; `503 face_service_unavailable` |
| `POST /api/v1/auth/password` | — (rate-limité) | `{challenge_id, password}` → `200 {access_token, token_type, expires_in, role}` (JWT avec claim `role`) ; `401 invalid_credentials` (cooldown **3 s**) ; `403 role_not_authorized` ; `409 wrong_step` ; `400 challenge_invalid` |
| `GET /api/v1/auth/device` | — (rate-limité) | `{led_online: bool\|null}` : statut du module LED (dernier heartbeat/LWT MQTT ; `null` si inconnu ou LED simulée) |
| `GET /api/v1/admin/users` | Bearer JWT, rôle `admin` | `200 [{username, role, enrolled, enrolled_at, enrolled_by}]` |
| `POST /api/v1/admin/users` | idem | `{username, password, role}` → `201 {username, role}` ; `409 username_taken` ; `422`. Aucun compte bancaire créé |
| `PATCH /api/v1/admin/users/{username}` | idem | `{role}` → `200 {username, role}` ; `404 unknown_user` ; `409 last_admin` |
| `PUT /api/v1/admin/users/{username}/face` | idem | `{poses:{face,gauche,droite}}` → `200 {enrolled:true, model_version}` ; `422 enrollment_rejected` + `details:[{pose,reason}]` ; `404 unknown_user` ; `503 face_service_unavailable` |
| `DELETE /api/v1/admin/users/{username}/face` | idem | `204` ; `404 not_enrolled` ; `409 last_admin` |
| `GET /api/v1/admin/users/{username}/face/photos` | idem | `200 {photos:{face,gauche,droite}}` ; `404 not_enrolled` |
| `GET /api/v1/auth/bootstrap` | — (rate-limité) | `200 {required}` ⇔ aucun admin enrôlé **et** `BACKOFFICE_BOOTSTRAP_TOKEN` configuré ; `503` si face-id injoignable |
| `POST /api/v1/auth/bootstrap` | token de bootstrap, `5/minute` | `{token, username, password, poses}` → `201 {username, role:"admin"}` ; `403 bootstrap_denied` (token faux, non requis, ou compte existant `customer`) ; `422 enrollment_rejected` (création annulée) |

JWT : **HS256**, secret `JWT_SECRET`, `exp` = 15 min, claims `sub` (username), `iat`, `exp` (+ `role` pour les jetons du back-office). Erreurs : `{"error":{"code","message","request_id"}}` (+ `details` pour `enrollment_rejected`).

### Consommées

- **PostgreSQL** (`postgres:5432/resilience`, réseau `data`) : tables `users` (colonne `role`), `accounts`.
- **`face-id`** (`FACE_ID_URL`, réseau `app`, header `X-Internal-Token`) via `FaceIdClient` : `verify` (3 frames), `enroll`, `revoke`, `enrollments`, `photos`. `auth` ne voit jamais d'embedding.
- **Broker MQTT Mosquitto** (`MQTT_HOST`/`MQTT_PORT`) : publie `resilience/led/cmd`, lit `resilience/led/status` (contrat §5.3). Fail-open.
- **Variables d'environnement / secrets** (SOPS) : `JWT_SECRET`, `INTERNAL_TOKEN`, `POSTGRES_PASSWORD`, `FACE_INTERNAL_TOKEN`, `MQTT_AUTH_PASSWORD`, `BACKOFFICE_BOOTSTRAP_TOKEN` (optionnel), tous avec variante `*_FILE`. Réglages : `FACE_ID_URL`, `BACKOFFICE_REJECT_COOLDOWN` (30), `BACKOFFICE_FAIL_COOLDOWN` (3), `BACKOFFICE_MAX_ATTEMPTS` (2), `BACKOFFICE_LOCKOUT_SECONDS` (300), `BACKOFFICE_CHALLENGE_TTL`, `BACKOFFICE_RATE_LIMIT`, `BACKOFFICE_FACE_REQUIRED`, `MQTT_HOST`, `MQTT_PORT`, `MQTT_USERNAME` (liste complète : README).
- **Appelants de l'API interne** : le moteur de remédiation (`remediation/actions/`), via le réseau `app` uniquement.

### Contrats transverses respectés

- **Logs (§1)** : events `auth_login_success` (INFO), `auth_login_failed` (WARNING), `auth_rate_limited` (WARNING) avec `ts, level, service="auth", event, message, request_id` + `user`, `client_ip`, `http_method`, `http_path`, `http_status`, `duration_ms`. Aucun mot de passe/hash/jeton journalisé.
- **Logs back-office (§1)** : `auth_identify_started`, `auth_face_recognized`, `auth_face_rejected`, `auth_locked_out`, `auth_cooldown`, `led_state_published`, `led_publish_failed`, et pour l'administration `admin_user_created`, `admin_role_changed`, `admin_face_enrolled`, `admin_face_revoked`, `backoffice_bootstrap` (champ `user` = compte ciblé, le message nomme l'acteur). Aucune image, aucun mot de passe, token ni embedding journalisé.
- **Métriques (§2)** : `resilience_auth_logins_total{result=success|failed}`, `resilience_auth_rate_limited_total`, `resilience_auth_face_steps_total{result}`, `resilience_auth_lockouts_total`, `resilience_led_publish_total{state,result}`, HTTP via `resilience_common.metrics.instrument(app,"auth")`.
- **API (§Conventions)** : `/api/v1`, `/health`, `/ready`, format d'erreur, JWT 15 min.

## 4. Sécurité

- **Mots de passe** : bcrypt (coût 12), jamais en clair ni journalisés ; longueur 8–72 octets (limite bcrypt refusée plutôt que tronquée).
- **Anti-énumération** : même réponse (code, message) pour « utilisateur inconnu » et « mauvais mot de passe » ; vérification bcrypt sur un hash factice pour égaliser le temps de réponse.
- **Rate-limit** `/login` par IP cliente (slowapi), appliqué **avant** le calcul bcrypt (le brute-force ne consomme pas le CPU). Défaut `10/minute`, configurable (`LOGIN_RATE_LIMIT`), resserrable par la remédiation.
- **IP cliente** : lue dans `X-Forwarded-For` **par la droite** (`TRUSTED_PROXY_HOPS`, défaut 1) ; la partie gauche, contrôlée par l'attaquant, est ignorée → un `X-Forwarded-For` forgé ne contourne pas le rate-limit. **Prérequis WAF** : il doit poser/ajouter l'IP source réelle.
- **Secrets** : aucun en dur ; `JWT_SECRET` ≥ 32 caractères et `INTERNAL_TOKEN` ≥ 16 exigés au démarrage (échec sinon) ; variantes `*_FILE` (secrets Docker/SOPS).
- **API interne** : token comparé en temps constant (`hmac.compare_digest`) ; **ne doit pas être routée par le WAF** ; refus journalisés.
- **Anti log-forging** : `X-Request-ID` entrant accepté seulement s'il s'agit d'un UUID ; sorties JSON échappées.
- **Erreurs de validation** : n'écho jamais la valeur reçue (un mot de passe n'apparaît pas dans un 422).
- **Accès back-office à étapes** : un `challenge_id` à usage unique (TTL `BACKOFFICE_CHALLENGE_TTL`) enchaîne identifiant → visage → mot de passe ; sauter une étape ou rejouer un challenge est refusé. Les **3 poses sont tirées dans un ordre aléatoire côté serveur** (CSPRNG) et les frames doivent suivre cet ordre : une photo statique unique ou une vidéo à ordre fixe ne suffit pas (mais 3 poses rejouées dans l'ordre affiché passent — résiduel EBIOS SO7, `docs/consigne-additionnelle-1.md` §7). Le mot de passe et un rôle `operator`/`admin` restent obligatoires (face-id seul n'ouvre rien).
- **Refroidissements et verrouillage** : visage refusé ⇒ attente **30 s** (par IP), mot de passe refusé ⇒ **3 s** ; **2 échecs** pour un `(identifiant, IP)` ⇒ verrouillage **300 s**, contrôlé à chaque étape (un challenge pré-créé ne le contourne pas).
- **Fail-closed du facteur visage** : face-id injoignable ⇒ `503 face_service_unavailable`, jamais d'ouverture par défaut. À l'inverse la **LED est fail-open** (témoin, pas un facteur).
- **Habilitations** : API `admin/*` réservée au rôle `admin` (JWT HS256 signé, `exp` obligatoire), rôle **revalidé en base** à chaque appel (une rétrogradation prend effet immédiatement). Garde **`last_admin`** : impossible de rétrograder ou de révoquer le visage du dernier administrateur enrôlé (enrôlement **utilisable** : `usable` de face-id) (sérialisée par un verrou pour éviter deux retraits concurrents). Les photos d'enrôlement ne transitent que sur demande d'un admin, la consultation est journalisée côté face-id.
- **Bootstrap** : désactivé si `BACKOFFICE_BOOTSTRAP_TOKEN` est vide ; sinon actif **uniquement tant qu'aucun admin enrôlé n'existe** ; token comparé en temps constant, `5/minute`. Un compte existant n'est repris que s'il est `operator`/`admin` (un `customer` est refusé, sans modification). Atomique : en cas d'échec, le gabarit éventuellement stocké par face-id est révoqué (sauf s'il préexistait), puis le compte est supprimé ou restauré ; un rollback en échec est journalisé (ERROR) sans masquer l'erreur d'origine.
- **Conteneur** : slim, non-root (uid 10001), compatible `read_only`, `cap_drop: ALL`, healthcheck ; docs OpenAPI désactivées par défaut.

## 5. Critères d'acceptation (chacun est couvert par un test)

| # | Critère | Test |
|---|---|---|
| A1 | Un utilisateur s'enregistre ; mot de passe stocké en bcrypt, compte à solde 0 | `test_register_creates_user_with_bcrypt_hash_and_account` |
| A2 | `409` si le nom existe ; `422` si entrée faible/mal formée, sans écho du mot de passe | `test_register_duplicate_…`, `test_register_rejects_weak_…` |
| A3 | `login` renvoie un JWT HS256, `sub` = username, validité 15 min | `test_login_returns_hs256_jwt_with_sub_and_15min_expiry` |
| A4 | Mauvais mot de passe ≡ utilisateur inconnu (401 indistinguables) | `test_login_wrong_password_and_unknown_user_are_indistinguishable` |
| A5 | Rate-limit : 429 après le seuil | `test_login_is_rate_limited_with_429_after_threshold` |
| A6 | 429 ⇒ log `auth_rate_limited` + métrique + erreur contrat + `Retry-After` | `test_rate_limit_emits_event_log_and_metric_and_contract_error` |
| A7 | Limite par IP ; `X-Forwarded-For` forgé sans effet | `test_rate_limit_is_per_client_ip`, `test_spoofed_leftmost_xff_cannot_evade_rate_limit` |
| A8 | `tighten` : token requis, limite × factor appliquée immédiatement, plancher 1, facteur invalide refusé, reset | `test_tighten_*`, `test_reset_restores_baseline_limit` |
| A9 | Logs conformes au contrat §1 (champs, ISO 8601, uuid, jamais de secret, events ∈ contrat) | `test_login_success_log_matches_contract_format`, `…failed_log…`, `test_all_emitted_events_belong_to_the_contract` |
| A10 | Métriques `resilience_auth_logins_total{result}` incrémentées | `test_login_metrics_increment_per_result` |
| A11 | `/health` ok ; `/ready` 503 si DB injoignable ; panne DB ⇒ 503 au format contrat | `test_health_and_ready_ok`, `test_ready_is_503_…`, `test_db_failure_…` |
| A12 | Comptes seedés (module réutilisable) peuvent se connecter | `test_seeded_accounts_can_log_in` |
| A13 | Migrations Alembic appliquées au démarrage | `test_lifespan_runs_alembic_migrations` |
| A14 | Config faible/absente refusée au démarrage | `test_settings_*` |

### Critères T3–T5 : authentification à étapes v2, LED, habilitations

| # | Critère | Test |
|---|---|---|
| A15 | Parcours complet identifiant → visage → mot de passe ⇒ JWT avec claim `role` ; séquence LED `idle → recognized → auth_ok` | `test_full_flow_identify_face_password_returns_token_with_role` |
| A16 | `identify` tire un ordre aléatoire des 3 poses ; exactement 3 frames exigées, dans l'ordre ; frames dans le désordre refusées sans appeler face-id | `test_identify_returns_random_permutation_of_three_poses`, `test_face_request_requires_exactly_three_frames`, `test_frames_out_of_order_are_rejected_without_calling_face_id`, `test_face_verifier_receives_ordered_frames` |
| A17 | Étapes non contournables, challenge à usage unique et expirant, identifiant inconnu indistinguable | `test_cannot_skip_face_step`, `test_face_challenge_cannot_be_replayed_after_match`, `test_expired_challenge_is_rejected`, `test_identify_unknown_user_still_returns_a_challenge` |
| A18 | Refroidissement **30 s** après visage refusé, **3 s** après mot de passe refusé, par IP, journalisé `auth_cooldown` | `test_face_rejection_starts_30s_cooldown_on_identify`, `test_wrong_password_starts_3s_cooldown`, `test_cooldown_logs_auth_cooldown_event`, `test_cooldown_does_not_affect_another_client_ip` |
| A19 | Verrouillage 5 min après 2 échecs, appliqué aussi aux challenges pré-créés ; succès remet à zéro ; fenêtre d'oubli | `test_lockout_after_one_retry_then_5_minutes`, `test_lockout_is_enforced_on_prebuilt_challenges`, `test_success_resets_the_failure_counter`, `test_failure_window_forgets_old_failures` |
| A20 | Rôle privilégié exigé ; mauvais mot de passe ⇒ LED rouge | `test_privileged_role_required`, `test_wrong_password_fails_and_lights_red` |
| A21 | Face-id indisponible ⇒ 503 (fail-closed) ; mode dégradé documenté ; `/login` inchangé | `test_face_service_unavailable_returns_503`, `test_degraded_mode_skips_face_step`, `test_legacy_login_still_works` |
| A22 | `FaceIdClient` : verify/enroll/revoke/enrollments/photos, token interne, 422 = refus, erreurs transport = `FaceUnavailable`, délais distincts | `tests/test_face_client.py` (`test_verify_*`, `test_enroll_*`, `test_revoke_*`, `test_enrollments_*`, `test_photos_*`) |
| A23 | LED MQTT : topics et payload du contrat §5.3, fail-open, `GET /api/v1/auth/device`, câblage par `MQTT_HOST` | `test_topics_follow_contract`, `test_publish_payload_topic_qos`, `test_publish_swallows_client_exception`, `test_status_messages_update_online`, `test_device_route_reports_led_online`, `test_mqtt_host_builds_mqtt_notifier`, `test_settings_from_env_mqtt` ; coupure ⇒ `led_online` inconnu, refus du broker journalisé sans secret, panne du démarrage LED non bloquante : `test_disconnect_resets_online_to_unknown`, `test_refused_connection_is_logged_without_secret_and_not_subscribed`, `test_led_start_failure_does_not_prevent_boot` |
| A24 | RBAC de l'API admin : sans jeton 401, `operator` 403, jeton invalide/expiré/forgé 401, rôle revalidé en base | `test_admin_routes_require_a_token`, `test_admin_routes_forbid_operator`, `test_invalid_expired_and_wrongly_signed_tokens_are_401`, `test_demoted_admin_with_still_valid_token_is_forbidden`, `test_decode_access_token_roundtrip_and_rejections` |
| A25 | Création/liste des comptes (sans compte bancaire), doublon 409, rôle/entrées invalides 422 | `test_create_user_then_listed_without_bank_account`, `test_list_users_includes_enrollment_state`, `test_create_user_duplicate_is_409`, `test_create_user_validation_is_422` |
| A26 | Changement de rôle journalisé ; garde `last_admin` (PATCH et DELETE face) ; 503 si face-id injoignable | `test_change_role_updates_db_and_logs`, `test_last_enrolled_admin_cannot_be_demoted`, `test_last_enrolled_admin_face_cannot_be_revoked`, `test_demotion_guard_face_unavailable_is_503` |
| A27 | Enrôlement relayé avec `enrolled_by` = administrateur ; rejet 422 avec `details` ; 404 ; 503 ; payload à exactement 3 poses | `test_enroll_face_relays_poses_and_actor`, `test_enroll_face_rejected_relays_details`, `test_enroll_face_unknown_user_is_404`, `test_enroll_face_unavailable_is_503`, `test_enroll_face_payload_must_have_exactly_the_three_poses` |
| A28 | Révocation 204/404 et consultation des photos (viewer = admin) | `test_revoke_face_204_and_log`, `test_revoke_face_not_enrolled_is_404`, `test_photos_returns_poses_and_logs_viewer`, `test_photos_not_enrolled_is_404` |
| A29 | Bootstrap : requis ⇔ aucun admin enrôlé et token configuré ; token faux/absent ⇒ 403 ; succès crée un admin enrôlé puis `required=false` ; enrôlement rejeté ⇒ création annulée ; limite 5/min | `test_bootstrap_status_*`, `test_bootstrap_wrong_token_is_403`, `test_bootstrap_without_configured_token_is_always_denied`, `test_bootstrap_creates_enrolled_admin_then_not_required`, `test_bootstrap_rejected_enrollment_rolls_back_creation`, `test_bootstrap_rejected_enrollment_restores_existing_user`, `test_bootstrap_refuses_existing_customer_account`, `test_bootstrap_existing_staff_gets_new_password_and_admin_role`, `test_bootstrap_failure_after_face_id_stored_revokes_and_deletes_new_user`, `test_bootstrap_failure_after_face_id_stored_restores_existing_user`, `test_bootstrap_failure_keeps_template_of_already_enrolled_account`, `test_bootstrap_rollback_failure_is_logged_and_original_error_is_returned`, `test_bootstrap_is_rate_limited_to_5_per_minute`, `test_bootstrap_token_is_read_from_env_or_file` |
| A31 | Seuls les enrôlements `usable` comptent (liste `enrolled`/`stale`, `last_admin`, bootstrap requis) | `test_list_users_marks_stale_enrollment_as_not_enrolled`, `test_enrollment_row_without_usable_flag_is_not_counted`, `test_stale_enrollment_does_not_count_for_the_last_admin_guard`, `test_bootstrap_required_when_admins_only_have_stale_enrollments` |
| A30 | Événements émis ∈ `RESERVED_EVENTS` ; aucun mot de passe, token ni image dans les logs | `test_all_emitted_events_belong_to_the_contract`, `test_admin_events_are_reserved_and_never_leak_secrets` |

Métriques HTTP conformes au contrat §2 : `resilience_common.metrics.instrument` produit les noms/labels exacts (`resilience_http_requests_total{service,method,path,status}`). Le test `test_http_metrics_follow_contract_names_and_labels` est actif et vert (l'ancien `xfail` est retiré).

## 6. Hors périmètre / limites assumées

- Rate-limit **en mémoire, par processus** (1 worker uvicorn) : un redémarrage (`restart_service`) remet la limite à sa valeur de référence ; passer à plusieurs réplicas imposerait un stockage partagé (Redis).
- Pas de refresh token, pas de révocation de JWT (durée courte 15 min ; pour l'API admin le rôle est néanmoins revalidé en base), MFA limitée au facteur visage du back-office.
- Challenges, verrouillages, refroidissements et le verrou `last_admin` sont **en mémoire, par processus** (1 worker) : un redémarrage les remet à zéro.
- La garde `last_admin` lit l'état d'enrôlement chez face-id ; un enrôlement/une révocation faits **directement** auprès de face-id (hors API admin) ne sont pas arbitrés par `auth`.
- `POST /register` n'est pas rate-limité (risque résiduel : création massive de comptes fictifs).
- Un corps de requête mal formé (422) est rejeté avant le rate-limit (coût négligeable : pas de bcrypt).
