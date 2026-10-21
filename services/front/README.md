# services/front - Front de paiement (React + Vite + TypeScript + Tailwind)

Interface utilisateur de la plateforme de paiement **fictive** « Banque Résilience » : connexion, accueil (solde), comptes, virement, historique. Quoi et pourquoi : [`CAHIER-DES-CHARGES.md`](CAHIER-DES-CHARGES.md). Contrats : [`docs/contracts.md`](../../docs/contracts.md).

## Lancement

```bash
cd services/front
npm install
cp .env.example .env      # optionnel
npm run dev               # http://localhost:5173
```

Le serveur de dev proxifie `/api/*` vers `DEV_API_TARGET` (défaut `http://localhost`, c'est-à-dire le WAF local de `make up`). Sans WAF, viser directement les services :

```bash
DEV_API_TARGET=http://localhost:8001 DEV_AUTH_TARGET=http://localhost:8002 npm run dev
```

Comptes de démo (seed) : `demo01`, `demo02` — mots de passe dans `scripts/seed.py`, jamais dans le front.

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

Maquettes Claude Design « Banque Résilience » (D1–D16) : `design/CLAUDE-DESIGN-PROMPT.md`, epic GitHub #52.
Un seul code pour **desktop** (≥ 1024 px : barre latérale) et **mobile** (barre d'onglets flottante, assistant d'envoi
en 4 étapes) ; le point de rupture est lu en JS (`useIsDesktop`) car les parcours diffèrent, pas seulement la mise en page.

```
src/
  main.tsx, App.tsx          routes : /login, /, /stats, /send, /history, /operations/:id, /rib, /profile
                             (anciennes /transfer -> /send, /accounts -> /rib)
  index.css                  jetons du design (@theme Tailwind v4 : couleurs, ombres, animations), utilitaires
                             (card, field, search, btn-primary, btn-ghost, round-btn), règles d'impression (RIB)
  config.ts                  API_BASE (VITE_API_BASE)
  types/api.ts               Account, Transaction (+ requestId), LoginResponse, TransferRequest, ApiErrorBody
  api/
    client.ts                client HTTP : Bearer, JSON, timeout, erreurs normalisées, signal de disponibilité
    errors.ts / parsers.ts   ApiError ; normalisation des réponses (centimes -> euros, iban_fake, request_id)
    tokenStore.ts            JWT en sessionStorage + lecture des claims sub/exp
    index.ts                 endpoints /api/v1 (login, accounts, transactions) + instance branchée sur serviceStatus
  hooks/                     useAuth, useResource, useAccounts, useTransactions (tri), useBankData, useTxViews,
                             useIsDesktop, useServiceStatus, useSecondsLeft, shell-context (toast, retour d'en-tête)
  components/
    Layout.tsx               shell : barre latérale (desktop) / onglets (mobile), en-tête, bandeau d'état, toasts
    BankDataProvider.tsx     comptes + transactions partagés, rafraîchis toutes les 15 s (onglet visible)
    ui.tsx                   AccountCard, TxRow, Segmented, Avatar, états chargement/vide/erreur, ConfirmDialog
    icons.tsx                pictogrammes SVG inline
  pages/                     Login, Home, Stats, Send (formulaire desktop + assistant mobile, glisser pour envoyer),
                             History (+ feuille de filtres mobile, export CSV), TxDetail, Rib, Profile
  lib/
    bank.ts                  vues métier pures : sens/montant signé, groupes par jour, dépenses par période,
                             destinataires connus, CSV (anti-injection de formules)
    serviceStatus.ts         état du service (ok / perturbé / rétabli) pour le bandeau D6
    format, validation, errorMessages, labels
  test/                      setup Vitest, helpers (stub fetch, faux JWT, setViewport desktop/mobile)
docker/                      nginx.conf (non-root, :8080), security-headers.conf
```

Flux d'authentification : `LoginPage` -> `AuthProvider.login` -> `POST /api/v1/login` -> JWT en `sessionStorage` -> `client.ts` ajoute `Authorization: Bearer`. Un `401` sur une route authentifiée, ou l'expiration du claim `exp`, vide le jeton et renvoie vers `/login` avec le message « Votre session a expiré ». Le libellé de virement n'existe pas dans l'API : il est gardé en `localStorage` (`resilience.labels`) et réaffiché dans l'historique.

**Bandeau d'état du service (démo).** Toute requête qui échoue côté serveur (réseau, timeout, 5xx) passe l'app en
« Service perturbé — reprise automatique en cours » ; la première réponse saine d'une requête partie *après* la panne
affiche « Service rétabli » (4 s) et recharge les données. Le rafraîchissement périodique (15 s) et une sonde de reprise
(5 s, seulement pendant l'incident) rendent l'incident et la reprise visibles **sans action de l'utilisateur**.

**Statut inconnu.** Sur timeout ou coupure réseau pendant `POST /transactions`, le virement a pu être exécuté
(payment-api n'a pas de clé d'idempotence) : l'écran de résultat renvoie vers l'historique au lieu de proposer
« Réessayer », pour éviter un double débit. Un 5xx explicite garde « Réessayer ».

**Données non fournies par l'API.** payment-api n'expose ni nom de compte, ni contrepartie nommée, ni catégorie,
ni plafond : l'UI affiche « Compte n°X » et masque les blocs correspondants (catégories, plafond, bénéficiaires,
cartes, notifications…) jusqu'aux tickets backend #43–#51, plutôt que d'afficher des données inventées.

## Tests

```bash
npm run test
```

- `src/api/client.test.ts` : Bearer, URL de base, erreur du contrat, repli non conforme (HTML du WAF), 401, réseau, timeout, 204.
- `src/api/endpoints.test.ts` : routes `/api/v1/*`, corps envoyés (centimes, ids entiers), parsing, claims JWT (`sub`, `exp`).
- `src/lib/bank.test.ts` : sens/montants signés, groupes par jour, dépenses de la semaine/du mois, destinataires, CSV anti-injection.
- `src/lib/serviceStatus.test.ts` : transitions perturbé → rétabli → masqué, réponses parallèles ignorées.
- `src/lib/clipboard.test.ts` : copie via `navigator.clipboard`, repli hors contexte sécurisé (démo en HTTP), échec signalé.
- `src/lib/validation.test.ts`, `format.test.ts`, `labels.test.ts` : règles du virement, formatage, libellés locaux.
- `src/App.test.tsx` (desktop **et** mobile via `setViewport`) : login OK/KO/vide, 401, déconnexion confirmée ; shell
  (barre latérale vs onglets) ; accueil chargement/erreur/réessai ; bandeau d'état (sur erreur et en l'absence d'action) ;
  historique (groupes, filtres, feuille mobile, détail + référence) ; RIB ; envoi desktop (validation, récapitulatif,
  POST, refus 409, erreur 503 + réessai, coupure réseau = statut inconnu sans réessai) ; assistant mobile 4 étapes avec « glisser pour envoyer » au clavier.

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
