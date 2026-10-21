# Cahier des charges — `services/auth`

## 1. Rôle

Service d'**authentification** de la plateforme de paiement fictive : crée des comptes, vérifie les identifiants et délivre des **JWT** consommés par `payment-api`. C'est aussi la **cible naturelle du scénario `auth_abuse`** (brute-force / credential stuffing) : il porte le rate-limit, produit les signaux de détection (`auth_failed_per_s`) et expose un point d'entrée interne permettant à la remédiation de **durcir la limite à chaud** (`tighten_rate_limit`).

- Port interne **8002**, réseau Docker **`app`** (+ `data` pour joindre PostgreSQL). Nom de service Compose : **`auth`**. Jamais exposé directement : seul le WAF l'est.

## 2. Exigences du sujet couvertes

| Réf. | Exigence | Comment |
|---|---|---|
| **R1** | SI de paiement fictif : auth, BDD, microservices conteneurisés | Service FastAPI conteneurisé, persistance PostgreSQL partagée (`libs/python/resilience_db`) |
| **R2** | (indirect) transaction traçable | Fournit l'identité (`sub`) et les comptes ; la traçabilité des virements est dans `payment-api` |
| **R7/R12** | Observabilité / fonction SOC | Logs JSON contrat §1 (`auth_login_*`, `auth_rate_limited`) + métriques §2 → règles Loki/Prometheus |
| **R8** | Détection ML | Alimente la feature `auth_failed_per_s` (via `resilience_auth_logins_total{result="failed"}`) |
| **R14/R15** | Durcissement / privilèges maîtrisés | Image non-root/slim/healthcheck, API interne protégée par token, comparaison en temps constant |

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

JWT : **HS256**, secret `JWT_SECRET`, `exp` = 15 min, claims `sub` (username), `iat`, `exp`. Erreurs : `{"error":{"code","message","request_id"}}`.

### Consommées

- **PostgreSQL** (`postgres:5432/resilience`, réseau `data`) : tables `users`, `accounts`.
- **Variables d'environnement / secrets** (SOPS) : `JWT_SECRET`, `INTERNAL_TOKEN`, `POSTGRES_PASSWORD`.
- **Appelants de l'API interne** : le moteur de remédiation (`remediation/actions/`), via le réseau `app` uniquement.

### Contrats transverses respectés

- **Logs (§1)** : events `auth_login_success` (INFO), `auth_login_failed` (WARNING), `auth_rate_limited` (WARNING) avec `ts, level, service="auth", event, message, request_id` + `user`, `client_ip`, `http_method`, `http_path`, `http_status`, `duration_ms`. Aucun mot de passe/hash/jeton journalisé.
- **Métriques (§2)** : `resilience_auth_logins_total{result=success|failed}`, `resilience_auth_rate_limited_total`, HTTP via `resilience_common.metrics.instrument(app,"auth")`.
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

Métriques HTTP conformes au contrat §2 : `resilience_common.metrics.instrument` produit les noms/labels exacts (`resilience_http_requests_total{service,method,path,status}`). Le test `test_http_metrics_follow_contract_names_and_labels` est actif et vert (l'ancien `xfail` est retiré).

## 6. Hors périmètre / limites assumées

- Rate-limit **en mémoire, par processus** (1 worker uvicorn) : un redémarrage (`restart_service`) remet la limite à sa valeur de référence ; passer à plusieurs réplicas imposerait un stockage partagé (Redis).
- Pas de refresh token, pas de révocation de JWT (durée courte 15 min), pas de MFA.
- `POST /register` n'est pas rate-limité (risque résiduel : création massive de comptes fictifs).
- Un corps de requête mal formé (422) est rejeté avant le rate-limit (coût négligeable : pas de bcrypt).
