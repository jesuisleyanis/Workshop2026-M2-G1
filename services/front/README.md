# services/front - Front de paiement (React + Vite + TypeScript + Tailwind)

Interface utilisateur de la plateforme de paiement **fictive** : connexion, solde, virement, historique. Quoi et pourquoi : [`CAHIER-DES-CHARGES.md`](CAHIER-DES-CHARGES.md). Contrats : [`docs/contracts.md`](../../docs/contracts.md).

## Lancement

```bash
cd services/front
npm install
cp .env.example .env      # optionnel
npm run dev               # http://localhost:5173
```

Le serveur de dev proxifie `/api/*` vers `DEV_API_TARGET` (défaut `http://localhost`, c'est-à-dire le WAF local de `make up`). Pour viser directement un service : `DEV_API_TARGET=http://localhost:8001 npm run dev`.

## Scripts

| Commande | Effet |
|---|---|
| `npm run dev` | Dev server (port 5173, strict) |
| `npm run build` | `tsc --noEmit` puis build Vite dans `dist/` |
| `npm run preview` | Sert `dist/` sur 5173 |
| `npm run lint` | ESLint (typescript-eslint + react-hooks) |
| `npm run typecheck` | Typage seul |
| `npm run test` | Vitest en mode run (CI, non-watch) |
| `npm run test:watch` | Vitest en watch |

## Variables `VITE_*`

| Variable | Défaut | Description |
|---|---|---|
| `VITE_API_BASE` | _vide_ (same-origin) | Préfixe de l'API, **figé au build**. `https://hote:443` si l'API est sur une autre origine |
| `DEV_API_TARGET` (non-Vite) | `http://localhost` | Cible du proxy de dev |

## Architecture

```
src/
  main.tsx, App.tsx          point d'entrée, routes (react-router)
  config.ts                  API_BASE (VITE_API_BASE)
  types/api.ts               Account, Transaction, LoginResponse, TransferRequest, ApiErrorBody
  api/
    client.ts                client HTTP centralisé : Bearer, JSON, timeout, erreurs normalisées
    errors.ts                ApiError + conversion du corps {error:{code,message,request_id}}
    parsers.ts               validation/normalisation des réponses (schémas métier)
    tokenStore.ts            JWT en sessionStorage + lecture du claim exp
    index.ts                 endpoints /api/v1 (login, accounts, transactions) + instance
  hooks/                     useAuth (+ contexte), useResource, useAccounts, useTransactions
  components/                AuthProvider, ProtectedRoute, Layout, BalanceCard, TransferForm,
                             TransactionTable, Field, Spinner, ErrorBanner
  pages/                     LoginPage, DashboardPage, TransferPage, HistoryPage
  lib/                       format (EUR/dates fr-FR), validation du virement, messages d'erreur
  test/                      setup Vitest, helpers (stub fetch, faux JWT)
docker/                      nginx.conf (non-root, :8080), security-headers.conf
```

Flux d'authentification : `LoginPage` -> `AuthProvider.login` -> `POST /api/v1/login` -> JWT en `sessionStorage` -> `client.ts` ajoute `Authorization: Bearer`. Un `401` sur une route authentifiée, ou l'expiration du claim `exp`, vide le jeton et renvoie vers `/login`.

## Tests

```bash
npm run test
```

- `src/api/client.test.ts` : Bearer, URL de base, erreur du contrat, repli non conforme (HTML du WAF), 401, réseau, timeout, 204.
- `src/api/endpoints.test.ts` : routes `/api/v1/*`, corps envoyés, parsing (décimaux en chaîne, listes enveloppées), `decodeJwtExp`.
- `src/lib/validation.test.ts` : règles du formulaire de virement.
- `src/App.test.tsx` : redirection, login OK/KO, chargement/erreur/réessai, déconnexion sur 401, virement (validation + envoi + refus serveur), historique.

## Docker (prod)

```bash
docker build -t resilience-front --build-arg VITE_API_BASE="" services/front
docker run --rm -p 8080:8080 --read-only --tmpfs /tmp resilience-front
curl -fsS http://localhost:8080/healthz      # ok
```

Image multi-stage : `node:22-alpine` (npm ci + build) -> `nginx:1.27-alpine` en utilisateur `nginx`, port **8080**, pid/temp dans `/tmp` (compatible `read_only`), CSP et en-têtes de sécurité, fallback SPA, `HEALTHCHECK` sur `/healthz`.

### Câblage compose / WAF

- Service `front` sur le réseau `app` uniquement, **sans `ports:`** (seul le WAF est publié).
- Le WAF proxifie : `location / { proxy_pass http://front:8080; }` et `location /api/v1/ { ... }` vers `auth:<port>` (`/api/v1/login`) et `payment-api:<port>` (`/api/v1/accounts`, `/api/v1/transactions`).
- Avec `VITE_API_BASE` vide, le navigateur appelle `/api/v1/...` sur la même origine que la page : pas de CORS à configurer.
- Durcissement conseillé : `read_only: true`, `tmpfs: [/tmp]`, `cap_drop: [ALL]`, `security_opt: [no-new-privileges:true]`, limites CPU/RAM.
