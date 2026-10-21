# Cahier des charges — `services/payment-api`

## 1. Rôle

API métier de la plateforme de paiement **fictive** : consultation des comptes, **virement fictif** (débit/crédit atomique, refus si solde insuffisant) et historique. C'est la **cible principale des scénarios d'attaque** (`service_flood`, `data_corruption`) et le support de la **transaction de vérification** (`scripts/verify_tx`) qui prouve le retour à la normale après remédiation.

- Port interne **8001**, réseau Docker **`app`** (+ `data` pour joindre PostgreSQL). Nom de service Compose : **`payment-api`**. Jamais exposé directement : seul le WAF l'est.

## 2. Exigences du sujet couvertes

| Réf. | Exigence | Comment |
|---|---|---|
| **R1** | SI de paiement fictif : API métier, BDD, conteneurisé | Service FastAPI conteneurisé + PostgreSQL (schéma `libs/python/resilience_db`, migrations Alembic) |
| **R2** | Transaction fictive initiable **et traçable** | `POST /api/v1/transactions` ; chaque virement (accepté **ou refusé pour solde**) est persisté avec `status` et `request_id` (corrélé aux logs) ; `GET /api/v1/transactions` |
| **R7/R12** | Observabilité / fonction SOC | Logs JSON `transaction_created/rejected`, `db_error` ; métriques `resilience_transactions_total`, `resilience_db_errors_total`, HTTP |
| **R8** | Détection ML | Alimente `req_per_s`, `p95_latency_ms`, `ratio_4xx/5xx`, `db_errors_per_s` |
| **R3** (support) | Retour à l'état utilisable prouvé | `/ready` + transaction de contrôle réussie |
| **R14** | Durcissement | JWT obligatoire sur toutes les routes métier, image non-root/slim/healthcheck, pas de secret en dur |

## 3. Interfaces

### Exposées (formats : [`docs/contracts.md`](../../docs/contracts.md))

| Méthode & chemin | Auth | Description |
|---|---|---|
| `GET /api/v1/accounts` | JWT | Comptes de l'utilisateur : `[{id, iban_fake, balance_cents, currency}]` |
| `POST /api/v1/transactions` | JWT | `{src_account, dst_account, amount_cents, category?}` → `201` transaction (`category` facultatif, défaut `transfer`, conservé aussi sur un refus). Refus : `409 limit_exceeded` (plafond mensuel #46, contrôlé sous verrou de la source ; virements internes exclus), `409 insufficient_funds`, `422 invalid_amount / amount_too_large / same_account / currency_mismatch`, `404 account_not_found / destination_not_found` |
| `GET /api/v1/transactions?limit=50` | JWT | Historique (transactions touchant un compte de l'utilisateur), plus récentes d'abord, `limit` 1–200 ; chaque ligne porte `category`, **masquée (`null`) pour le destinataire** (catégorisation privée de l'émetteur) |
| `GET /api/v1/transactions/{id}` | JWT | Détail (#45) : émetteur ou destinataire seulement ; tiers et id inconnu = même `404 transaction_not_found` (pas de 403 : pas d'oracle d'existence), tracé `transaction_access_denied` (`unknown`/`foreign`) ; une seule requête SQL (opération + titulaires) |
| `GET /api/v1/cards` | JWT | Cartes de l'utilisateur (#47) : `last4`, titulaire, expiration, statut, réglages — jamais de PAN ni de CVV |
| `POST /api/v1/cards/{id}/freeze` · `/unfreeze` | JWT | Gel / dégel idempotents ; carte d'autrui = `404 card_not_found` |
| `PATCH /api/v1/cards/{id}` | JWT | Réglages partiels bornés (plafond 0–10 000 €, sans contact, paiement en ligne) ; champ inconnu → `422` ; carte gelée → `409 card_frozen` |
| `GET`·`POST /api/v1/scheduled-transfers`, `PATCH`·`DELETE /{id}` | JWT | Virements programmés (#48) : création validée (dates, montants, comptes), pause/reprise, annulation ; exécutés par la tâche de fond `schedules.run_due` |
| `GET /api/v1/limits` | JWT | Plafond mensuel par compte (#46) : plafond (`null` = aucun), consommé du mois, restant, date de remise à zéro |
| `GET /api/v1/stats/spending?period=week\|month&offset=0` | JWT | Dépenses d'une période (#44 ; `offset` ∈ [-24, 0]) : total, parts par catégorie (décroissant), série journalière complète. Dépense = virement `created` vers un compte d'un autre client ; périodes UTC `[start, end)` ; **agrégation SQL** (coût borné quel que soit l'historique) |
| `GET /api/v1/beneficiaries` | JWT | Bénéficiaires de l'utilisateur (#43), triés par nom |
| `POST /api/v1/beneficiaries` | JWT | `{display_name, iban_fake}` → `201`. IBAN ramené à la forme stockée (groupes de 4) : recherche exacte sur l'index unique, sans balayage. Refus : `404 account_not_found` (IBAN inconnu), `409 beneficiary_exists` (contrôle + contrainte BDD : sûr en concurrence ; toute autre violation d'intégrité = `503 db_unavailable`), `422 own_account`, `409 beneficiary_limit` (100/client). Piste d'audit : `beneficiary_added` / `beneficiary_rejected` (motif seul, **jamais l'IBAN sondé**) / `beneficiary_removed` |
| `DELETE /api/v1/beneficiaries/{id}` | JWT | `204` ; objet d'autrui = `404 beneficiary_not_found` (anti-IDOR). Id borné à l'INTEGER Postgres (`422` au-delà, jamais un faux `db_error`) |
| `GET /api/v1/status` | **aucune** | État public pour le bandeau client (#42) : `200 {status:"ok", checked_at}` / `503 {status:"degraded", checked_at}`. Rien d'autre (pas de version, d'hôte ni d'exception). Cache `STATUS_CACHE_S` = 2 s : **au plus une requête BDD par fenêtre**, quel que soit le trafic (pas d'amplification) ; le WAF limite en plus par IP |
| `GET /health` | — | Liveness |
| `GET /ready` | — | `200` si la DB répond ; `503 db_unavailable` sinon |
| `GET /metrics` | — (réseau interne) | Prometheus |

Erreurs : `{"error":{"code","message","request_id"}}`. Montants en **centimes entiers** (les flottants/booléens sont refusés en 422).

### Consommées

- **JWT émis par `auth`** : HS256, secret partagé `JWT_SECRET`, claim `sub` = username, `exp` obligatoire. Pas d'appel réseau à `auth` : validation locale de la signature + existence du compte en base.
- **PostgreSQL** (`postgres:5432/resilience`, réseau `data`) : tables `users`, `accounts`, `transactions`.
- **Secrets** : `JWT_SECRET`, `POSTGRES_PASSWORD`.

### Contrats transverses respectés

- **Logs (§1)** : `transaction_created` (INFO), `transaction_rejected` (WARNING, motif dans `message`), `db_error` (ERROR) avec `ts, level, service="payment-api", event, message, request_id` + `user`, `client_ip`, `http_*`, `duration_ms`.
- **Métriques (§2)** : `resilience_transactions_total{result=created|rejected}`, `resilience_db_errors_total`, HTTP via `resilience_common.metrics.instrument(app,"payment-api")`.
- **API** : `/api/v1`, `/health`, `/ready`, format d'erreur.

## 4. Règles métier

1. Le **débit** n'est possible que depuis un compte **appartenant à l'appelant** (compte tiers ⇒ même `404` qu'un compte inexistant, pas d'oracle d'existence).
2. `amount_cents` ∈ ]0 ; 100 000 000] ; compte source ≠ destination ; même devise.
3. **Solde insuffisant ⇒ refus** (`409`), soldes inchangés, tentative tracée (`status=rejected`) + event `transaction_rejected` + métrique `rejected`.
4. Débit + crédit + ligne `transactions` dans **une seule transaction SQL** ; verrous de ligne (`SELECT … FOR UPDATE`) pris **dans l'ordre des id** (pas de double dépense concurrente, pas de deadlock) ; `CHECK balance_cents >= 0` en filet de sécurité côté DB.
5. Toute erreur SQLAlchemy sur une route métier ⇒ `503 db_unavailable`, event `db_error`, métrique `resilience_db_errors_total` (jamais de requête SQL dans la réponse ni les logs).

## 5. Sécurité

- **JWT obligatoire** sur toutes les routes métier via **une dépendance commune** (`current_user`) : absent, mal formé, signature invalide, expiré, `sub` manquant, utilisateur inconnu ⇒ `401` (`missing_token` / `invalid_token` / `token_expired`) + `WWW-Authenticate`.
- Algorithme **épinglé à HS256** (jeton `alg: none` rejeté), `exp` et `sub` requis, secret ≥ 32 caractères exigé au démarrage.
- Isolation entre utilisateurs (comptes et historique filtrés par propriétaire).
- Logs : jamais de jeton, de secret ni de SQL ; `X-Request-ID` entrant accepté seulement s'il s'agit d'un UUID (anti log-forging) ; IP cliente lue depuis la droite de `X-Forwarded-For` (`TRUSTED_PROXY_HOPS`).
- Sonde `/ready` **n'alimente pas** `resilience_db_errors_total` (les healthchecks ne doivent pas fabriquer un signal d'anomalie).
- Conteneur : slim, non-root (uid 10001), compatible `read_only` + `cap_drop: ALL`, healthcheck, docs OpenAPI désactivées par défaut.

## 6. Critères d'acceptation (chacun est couvert par un test)

| # | Critère | Test (fichier) |
|---|---|---|
| B1 | Routes métier : `401` sans jeton / jeton invalide / expiré / sans `sub` / utilisateur inconnu / `alg:none` / schéma non-Bearer | `test_payment_auth.py` |
| B2 | Jeton valide au format émis par `auth` accepté ; `/health` `/ready` sans auth | `test_valid_token_from_auth_service_is_accepted`, `test_probes_do_not_require_auth` |
| B3 | Virement : débit + crédit atomiques, `request_id` tracé | `test_transfer_debits_source_and_credits_destination_atomically` |
| B4 | **Solde insuffisant ⇒ refus**, soldes inchangés, tentative persistée | `test_insufficient_funds_is_rejected_and_balances_untouched` |
| B5 | Montant nul/négatif/trop grand, même compte, devise, compte tiers, destinataire inconnu refusés | `test_non_positive_amount…`, `test_amount_above_maximum…`, `test_same_account…`, `test_cannot_spend_from_someone_elses_account`, … |
| B6 | Montants non entiers refusés (422) | `test_non_integer_amounts_are_422_validation_errors` |
| B7 | Historique : filtré par propriétaire, ordre, `limit` | `test_history_*` |
| B8 | Métrique `resilience_transactions_total{result}` incrémentée | `test_transaction_metrics_increment_per_result` |
| B9 | Logs `transaction_created` / `transaction_rejected` conformes au contrat §1 ; events ∈ contrat | `test_payment_contracts.py` |
| B10 | Panne DB ⇒ `503` contrat + event `db_error` + métrique `db_errors_total` ; `/ready` 503 sans compter ; `/health` reste 200 | `test_db_error_emits_event_metric_and_503_contract_error`, `test_ready_is_503_…` |
| B11 | `CHECK` DB empêche un solde négatif | `test_db_check_constraint_is_a_backstop_against_negative_balance` |
| B12 | Migrations Alembic au démarrage | `test_lifespan_runs_alembic_migrations` |
| B13 | **PostgreSQL réel** : virements concurrents sans découvert (optionnel, `TEST_POSTGRES_URL`) | `test_payment_postgres_integration.py` |

Métriques HTTP conformes au contrat §2 : `resilience_common.metrics.instrument` produit les noms/labels exacts (`resilience_http_requests_total{service,method,path,status}`). Le test `test_http_metrics_follow_contract_names_and_labels` est actif et vert (l'ancien `xfail` est retiré).

## 7. Hors périmètre / limites assumées

- Pas d'idempotence des virements (un rejeu crée une seconde transaction), pas de création/clôture de comptes (rôle d'`auth` + seed), pas de pagination par curseur.
- Pas de rate-limit applicatif propre : la protection contre le flood relève du WAF et de la remédiation (`service_flood`).
- Validation de `sub` sans révocation de jeton (durée de vie 15 min).
