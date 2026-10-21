# Cahier des charges - `services/front` (front de paiement)

> Exigence tracée : **R1** (SI de paiement fictif : front, API métier, auth, BDD, microservices conteneurisés). Contrats : [`docs/contracts.md`](../../docs/contracts.md). Cadrage global : [`CAHIER-DES-CHARGES.md`](../../CAHIER-DES-CHARGES.md).

## 1. Rôle

Interface web **utilisateur** de la plateforme de paiement fictive. Elle permet de se connecter, consulter son solde, émettre un virement fictif et consulter l'historique. C'est la **cible légitime** de la démo : le trafic normal (et la transaction de vérification côté `scripts/verify_tx`) passe par les mêmes routes `/api/v1/...` que celles consommées ici. Toutes les données sont fictives.

Le front est un **site statique** (build Vite) servi par nginx **derrière le WAF** (seul point exposé, R11/R19). Il n'embarque aucun secret ; le JWT est obtenu à l'exécution.

## 2. Exigences (R1)

| # | Exigence | Réalisation |
|---|---|---|
| F1 | Page de connexion appelant `POST /api/v1/login`, stockage du JWT | `LoginPage`, `AuthProvider`, `api/tokenStore.ts` (sessionStorage) |
| F2 | Accueil : « Bonjour », carrousel de comptes, solde total, « Envoyer à », dépenses du mois, opérations récentes | `HomePage` |
| F3 | Envoi `POST /api/v1/transactions` : desktop = formulaire une page + récapitulatif ; mobile = assistant 4 étapes + « glisser pour envoyer » ; écrans de résultat (envoyé / refusé solde / refusé / erreur 5xx + réessai / statut inconnu sur timeout-réseau, sans réessai pour éviter un double débit) | `SendPage`, `lib/validation.ts` |
| F4 | Historique groupé par jour, recherche, filtres statut/sens (feuille sur mobile), export CSV, détail d'opération + référence `request_id` copiable ; opération hors des 50 dernières (lien direct) chargée par `GET /api/v1/transactions/{id}` (#45, 404 = « introuvable »), comptes affichés avec **IBAN masqué** (`maskIban`) | `HistoryPage`, `TxDetailPage`, `lib/bank.ts`, `lib/format.ts` |
| F5 | Auth Bearer sur toutes les routes métier | `api/client.ts` |
| F6 | Gestion des erreurs (corps `{error:{code,message,request_id}}`, 401, 409 `insufficient_funds`, 429, réseau, timeout) | `api/errors.ts`, `components/ui.tsx` (`ErrorState`), `lib/errorMessages.ts` |
| F7 | États de chargement (squelettes), vides et de réessai sur chaque écran | `components/ui.tsx`, `hooks/useResource.ts`, `BankDataProvider` |
| F8 | Déconnexion sur 401 et à l'expiration du JWT (15 min), compte à rebours de session, déconnexion confirmée | `AuthProvider` + `setUnauthorizedHandler`, `Layout`, `ProfilePage` |
| F9 | Base d'API configurable (`VITE_API_BASE`) | `config.ts` |
| F10 | Image durcie : non-root, healthcheck, statique | `Dockerfile`, `docker/` |
| F11 | RIB par compte (#45) : titulaire, IBAN et BIC fictifs, copier / partager (Web Share API, repli copie) / imprimer (CSS `@media print`, compatible CSP) | `RibPage` |
| F12 | Libellé de virement (absent de l'API) conservé localement | `lib/labels.ts` (localStorage, par id de transaction) |
| F13 | Shell responsive : barre latérale ≥ 1024 px, barre d'onglets en dessous | `Layout`, `hooks/useMediaQuery.ts` |
| F14 | Statistiques : dépenses par jour (semaine/mois, navigation), opérations de la période | `StatsPage`, `lib/bank.ts` |
| F15 | Bandeau d'état du service (#42) : « perturbé » sur réseau/timeout/5xx de **n'importe quel** appel (dont le rafraîchissement 15 s des données), puis sonde `GET /api/v1/status` (public, sans jeton) toutes les 5 s tant que le service est perturbé ; « rétabli » seulement quand `GET /api/v1/accounts` répond aussi (un 200 de la sonde, ou un 429 du WAF, ne vaut pas reprise : `reportRecovery: false`), puis rechargement des données et auto-masquage. Aucune sonde en régime normal (pas de trafic ajouté à la baseline ML) | `lib/serviceStatus.ts`, `Layout`, `BankDataProvider`, `api.getStatus` |
| F16 | Bénéficiaires (#43, D7) : liste + recherche nom/IBAN, ajout (nom + IBAN ; erreurs « IBAN inconnu », « déjà enregistré », « votre propre compte »), suppression confirmée, « Envoyer » ; ils alimentent « Envoyer à » et l'écran Envoyer (avant les comptes déjà crédités) | `BeneficiariesPage`, `lib/bank.recipients`, `BankDataProvider` |
| F17 | Catégories de dépenses (#44, D8) : 9 catégories (icône + gris), sélecteur réutilisable (`aria-pressed`, flèches) dans Envoyer (desktop + étape « Détails » mobile, défaut « Virement », non envoyé au POST car défaut serveur), filtre de l'historique (desktop + feuille mobile + pastille ; **dépenses seulement** : un virement reçu n'a pas de catégorie, l'API masque celle de l'émetteur), catégorie sur la fiche d'une opération émise ; Statistiques : section « Catégories » (parts %, total) **calculée par payment-api** (`GET /api/v1/stats/spending?offset=`) pour la période affichée (navigation semaine/mois précédents), rechargée à la reprise du service ; accueil : total et 1re catégorie du mois sur la **même base serveur** (« Alimentation 73 % »), part masquée si vide/erreur. Catégorie absente d'un ancien serveur = « Virement », inconnue (serveur plus récent) = « Autre » | `lib/categories.ts`, `CategoryPicker`, `useSpending`, `SendPage`, `HistoryPage`, `StatsPage`, `HomePage` |
| F18 | Plafonds de virement (#46, D10) : barre « Plafond restant » sur l'accueil (compte débité par défaut : restant / plafond, % restant, remise à zéro ; « Sans plafond » pour un compte de service, rien si indisponible), écran `/limits` par compte (plafond, consommé, restant, remise à zéro), avertissement **non bloquant** dans Envoyer si le montant dépasse le restant connu (le serveur reste l'autorité), refus `409 limit_exceeded` = « Virement refusé — plafond mensuel atteint » ; plafonds rechargés après chaque virement, en cas d'échec (tick 15 s) et à la reprise du service. Raccourci de connexion `demo03` (client avec plafond ; `demo01`/`demo02` = comptes de service sans plafond) | `LimitBar`, `LimitsPage`, `lib/limits.ts`, `BankDataProvider`, `SendPage`, `HomePage` |
| F19 | Cartes (#47, D11) : visuel de carte noire (`•••• •••• •••• 4001`, titulaire, expiration MM/AA — jamais de numéro complet ni de CVV), état **gelée** distinct (visuel atténué + pastille), Geler / Dégeler avec confirmation, réglages : plafond de paiement (curseur 0–10 000 €, pas de 50 €, envoyé en centimes), sans contact et paiement en ligne (`Switch` accessible, `role=switch`) ; réglages verrouillés quand la carte est gelée ; messages dédiés `409 card_frozen` / `422` ; cartes chargées par l'écran (pas dans le `BankDataProvider`), sous-titre dans Profil | `CardsPage`, `Switch`, `useCards` |
| F20 | Virements programmés (#48, D12) : écran `/scheduled` (destinataire nommé, montant, fréquence « Une fois / Chaque semaine / Chaque mois », prochaine exécution, fin, statut en pastille, **dernière exécution échouée avec motif** — solde insuffisant, plafond atteint…), Pause / Reprendre (`PATCH`), Annuler confirmé (`DELETE`, la programmation reste listée « Annulée ») ; création depuis Envoyer via l'option « Programmer » (desktop + étape Détails mobile : fréquence, début par défaut aujourd'hui, fin facultative) → `POST /api/v1/scheduled-transfers`, écran « Virement programmé » ; `invalid_dates` / `schedule_limit` renvoient au formulaire avec un message clair. Le virement immédiat reste le défaut. L'exécution est faite par payment-api (aucun déclenchement côté front) ; parser en échec fermé (statut/fréquence inconnus) | `ScheduledPage`, `useSchedules`, `lib/schedules.ts`, `SendPage` |

### Design

Maquettes Claude Design « Banque Résilience » (D1–D16, desktop 1280 et mobile 390, prompt `design/CLAUDE-DESIGN-PROMPT.md`) :
noir & blanc, cartes de compte « nuit », grands rayons, ombres douces. Jetons, animations et utilitaires
(`card`, `field`, `search`, `btn-primary`, `btn-ghost`, `round-btn`, `tnum`) dans `src/index.css` (`@theme` Tailwind v4).
Écrans livrés : D1, D2, D3, D4, D5, D6, D7 (bénéficiaires), D8 (catégories), D9 (détail + RIB), D10 (plafonds), D11 (cartes), D12 (virements programmés), D16. Les écrans D13–D15 attendent leurs routes
backend (#49–#51) : aucune donnée n'est inventée côté front.
Polices **auto-hébergées** (`@fontsource`) : la CSP (`style-src 'self'`) interdit les CDN de polices.
Écart volontaire à la maquette : les raccourcis « comptes de démonstration » ne remplissent que l'**identifiant** —
aucun mot de passe n'est embarqué dans le bundle, servi publiquement derrière le WAF (donc lisible depuis le PC Attaquant).

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

### Schéma des corps métier (aligné sur `payment-api` / `auth`)

Le contrat `docs/contracts.md` fige les routes, l'auth et les erreurs, **pas** les corps métier.
Ceux-ci sont ceux réellement émis par `payment-api` (`AccountOut`, `TransactionIn`, `TransactionOut`) et `auth` :
les montants transitent en **centimes entiers**, les comptes sont identifiés par un **id entier**
(`iban_fake` sert de libellé affiché). Le front raisonne en euros : la conversion centimes ↔ euros
et le renommage des champs sont isolés dans `src/api/parsers.ts` + `src/api/index.ts`.

```jsonc
// POST /api/v1/login  { "username": "...", "password": "..." }
//   -> { "access_token": "<jwt>", "token_type": "bearer", "expires_in": 900 }   // "token" accepté en alias
// GET /api/v1/accounts -> [ { "id": 1, "iban_fake": "FR76 …", "balance_cents": 100000, "currency": "EUR" } ]
// POST /api/v1/transactions  { "src_account": <int>, "dst_account": <int>, "amount_cents": <int> }
//   -> { "id", "src_account", "dst_account", "amount_cents", "status": "created"|"rejected", "created_at"? }
// GET /api/v1/transactions -> [ <transaction> ]   // ou { "transactions": [...] }
```

Les parsers restent tolérants (centimes ou euros, liste nue ou enveloppée, `created_at` optionnel) pour
absorber une évolution mineure sans casse. Un écart de schéma reste isolé dans `src/api/parsers.ts`
(un seul fichier à ajuster) et couvert par `src/api/endpoints.test.ts`. Codes d'erreur métier reconnus :
`insufficient_funds` (409, carte « Virement refusé »), `invalid_credentials`, `validation_error` (sinon le `message` serveur est affiché).

> **Dev sans WAF** — le front Vite peut viser directement les services : `DEV_AUTH_TARGET` (login/register → `auth`)
> et `DEV_API_TARGET` (accounts/transactions → `payment-api`). Si `DEV_AUTH_TARGET` est absent, tout passe par
> `DEV_API_TARGET` (comportement WAF inchangé). Voir `vite.config.ts`.

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

Client API (fetch mocké : Bearer, erreurs du contrat, 401, réseau, timeout), parseurs (schémas, claims JWT), validation du virement, formatage, libellés locaux, parcours UI (redirection login + message de garde, connexion OK/KO/champs vides, déconnexion manuelle et sur 401, chargement/erreur/réessai, comptes → virement pré-rempli, virement OK / refus 409 / erreur serveur, historique trié et filtré). Lancement : `npm run test`. Détails dans le [`README.md`](README.md).
