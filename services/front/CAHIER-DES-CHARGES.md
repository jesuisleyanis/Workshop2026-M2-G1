# Cahier des charges - `services/front` (front de paiement)

> Exigence tracée : **R1** (SI de paiement fictif : front, API métier, auth, BDD, microservices conteneurisés). Contrats : [`docs/contracts.md`](../../docs/contracts.md). Cadrage global : [`CAHIER-DES-CHARGES.md`](../../CAHIER-DES-CHARGES.md).

## 1. Rôle

Interface web **utilisateur** de la plateforme de paiement fictive. Elle permet de se connecter, consulter son solde, émettre un virement fictif et consulter l'historique. C'est la **cible légitime** de la démo : le trafic normal (et la transaction de vérification côté `scripts/verify_tx`) passe par les mêmes routes `/api/v1/...` que celles consommées ici. Toutes les données sont fictives.

Le front est un **site statique** (build Vite) servi par nginx **derrière le WAF** (seul point exposé, R11/R19). Il n'embarque aucun secret ; le JWT est obtenu à l'exécution.

## 2. Exigences (R1)

| # | Exigence | Réalisation |
|---|---|---|
| F1 | Page de connexion appelant `POST /api/v1/login`, stockage du JWT | `LoginPage`, `AuthProvider`, `api/tokenStore.ts` (sessionStorage) |
| F2 | Tableau de bord : solde via `GET /api/v1/accounts` | `DashboardPage`, `BalanceCard` |
| F3 | Formulaire de virement fictif `POST /api/v1/transactions` | `TransferPage`, `TransferForm`, `lib/validation.ts` |
| F4 | Historique `GET /api/v1/transactions` | `HistoryPage`, `TransactionTable` |
| F5 | Auth Bearer sur toutes les routes métier | `api/client.ts` |
| F6 | Gestion des erreurs (corps `{error:{code,message,request_id}}`, 401, 429, réseau, timeout) | `api/errors.ts`, `ErrorBanner`, `lib/errorMessages.ts` |
| F7 | États de chargement et de réessai | `Spinner`, `hooks/useResource.ts` |
| F8 | Déconnexion sur 401 et à l'expiration du JWT (15 min) | `AuthProvider` + `setUnauthorizedHandler` |
| F9 | Base d'API configurable (`VITE_API_BASE`) | `config.ts` |
| F10 | Image durcie : non-root, healthcheck, statique | `Dockerfile`, `docker/` |

Non-objectifs : aucune logique métier (le serveur est l'autorité : solde, plafonds, rate-limit), pas de stockage de mot de passe, pas de vrai paiement.

## 3. Interfaces consommées

Toutes les routes passent par le préfixe `/api/v1` (contrat « Conventions d'API REST »), auth par `Authorization: Bearer <JWT>` (HS256, 15 min). Erreurs au format `{ "error": { "code", "message", "request_id" } }`.

| Route | Méthode | Auth | Usage |
|---|---|---|---|
| `/api/v1/login` | POST | non | Obtention du JWT (service `auth`) |
| `/api/v1/accounts` | GET | Bearer | Comptes et soldes (service `payment-api`) |
| `/api/v1/transactions` | GET | Bearer | Historique |
| `/api/v1/transactions` | POST | Bearer | Virement fictif |

Le front ignore quel microservice répond : c'est le **WAF** (ou le proxy Vite en dev) qui route `/api/v1/*`. Les statuts attendus et leur traitement : `401` => déconnexion et retour au login ; `429` (`auth_rate_limited` côté auth) => message « trop de tentatives » ; `5xx` / réseau / timeout => bandeau d'erreur + bouton Réessayer. Un `403` du WAF (page HTML, corps non conforme) est converti en `ApiError` générique `http_403`.

### Hypothèses de schéma (à confirmer avec `payment-api` / `auth`)

Le contrat fige les routes, l'auth et les erreurs, **pas** les corps métier. Le front suppose :

```jsonc
// POST /api/v1/login  { "username": "...", "password": "..." }
//   -> { "access_token": "<jwt>", "token_type": "bearer", "expires_in": 900 }   // "token" accepté en alias
// GET /api/v1/accounts -> [ { "id": "FR01", "label": "Compte courant", "balance": 1250.50, "currency": "EUR" } ]   // ou { "accounts": [...] }
// POST /api/v1/transactions  { "from_account", "to_account", "amount", "currency"?, "label"? }
//   -> { "id", "from_account", "to_account", "amount", "currency", "status": "created"|"rejected", "label"?, "created_at" }
// GET /api/v1/transactions -> [ <transaction> ]   // ou { "transactions": [...] }
```

Les montants peuvent être des nombres ou des chaînes décimales. Un écart de schéma est isolé dans `src/api/parsers.ts` (un seul fichier à ajuster) et couvert par `src/api/endpoints.test.ts`. Codes d'erreur métier reconnus : `insufficient_funds`, `invalid_credentials`, `validation_error` (sinon le `message` serveur est affiché).

## 4. Variables d'environnement

| Variable | Quand | Défaut | Rôle |
|---|---|---|---|
| `VITE_API_BASE` | **build** | _vide_ | Préfixe d'URL de l'API. Vide = same-origin (prod derrière le WAF). Ex. `https://192.168.137.1` pour une API sur un autre hôte |
| `DEV_API_TARGET` | dev | `http://localhost` | Cible du proxy Vite pour `/api` (WAF local ou service direct) |

`VITE_API_BASE` est figée dans le bundle à la construction (`--build-arg VITE_API_BASE=...`), pas modifiable au runtime.

## 5. Exécution et exposition

- Dev : `npm run dev` sur le port **5173** (proxy `/api` vers `DEV_API_TARGET`).
- Prod : conteneur nginx non-root écoutant **8080** (HTTP interne), réseau `app`, **non publié** sur l'hôte. Le WAF route `/` vers `front:8080` et `/api/v1/*` vers les APIs. Healthcheck : `GET /healthz` (200 `ok`).

## 6. Sécurité

- Image multi-stage `node:22-alpine` (build) -> `nginx:1.27-alpine` (runtime), utilisateur `nginx`, aucune dépendance Node à l'exécution, pas de shell applicatif.
- En-têtes : CSP stricte (`default-src 'self'`, pas de script inline), `X-Frame-Options: DENY`, `nosniff`, `Referrer-Policy: no-referrer`; `server_tokens off`.
- JWT en `sessionStorage` (durée de vie 15 min, effacé à la fermeture de l'onglet, purge sur 401/expiration). Aucun secret ni identifiant en clair dans le code ou l'image.
- Recommandation compose : `read_only: true` avec `tmpfs: /tmp`, `cap_drop: [ALL]`, limites CPU/RAM, `no-new-privileges` (l'image n'écrit que dans `/tmp`).
- Le front ne contourne jamais le WAF : l'attaque de la démo cible ces mêmes routes.

## 7. Tests (Vitest + Testing Library)

Client API (fetch mocké : Bearer, erreurs du contrat, 401, réseau, timeout), parseurs (schémas), validation du virement, parcours UI (redirection login, connexion OK/KO, chargement/erreur/réessai, 401 => logout, virement, historique). Lancement : `npm run test`. Détails dans le [`README.md`](README.md).
