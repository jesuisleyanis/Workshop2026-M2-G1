# services/payment-api/loadtest

Harnais de **test de charge** de l'API de paiement. Mesure *débit*, *latence*
(p50/p95/p99/max) et *taux d'erreur* sous charge concurrente, avec des **portes SLO**
qui font échouer la commande (code 2) si un seuil est dépassé. Cadrage et critères
d'acceptation : [`CAHIER-DES-CHARGES.md`](CAHIER-DES-CHARGES.md).

Deux cibles, un même générateur (`loadgen.py`) :

| Cible | Comment | Pour quoi |
|---|---|---|
| **in-process** (défaut) | construit la *vraie* app FastAPI (`create_app`) sur une base **SQLite fichier** (WAL, multi-connexions) seedée, pilotée via le transport **ASGI** de httpx — aucun serveur, aucun port, aucun Docker | tourner **sur le poste de dev** (pas de Docker — cf. [`docs/pca-pra.md`](../../../docs/pca-pra.md)), en CI locale, et comme filet anti-régression |
| **live** (`--url`) | tape une instance **réellement déployée** en HTTP : login réel (`POST /api/v1/login`) + découverte des comptes (`GET /accounts`) | **recette J3/J4** sur la stack réelle (PostgreSQL, WAF), mesure des cibles RTO/capacité |

> Le mode in-process mesure la chaîne **app + ORM + SQLite** : les chiffres absolus sont
> dominés par SQLite (un seul *writer*), **non représentatifs de PostgreSQL**. De plus, les
> routes sync de FastAPI s'exécutent dans le **threadpool anyio (~40 jetons)** : au-delà de
> `-c 40`, la concurrence *effective* plafonne et la latence enfle par mise en file — ce
> n'est pas de la concurrence serveur réelle. Le mode in-process valide le **comportement**
> (0 erreur serveur, latences stables, montée en charge) ; les **chiffres de capacité
> officiels** se prennent en mode `--url` contre la stack réelle.

## Lancer

Depuis `services/payment-api/` (environnement Python du service installé — cf. le
[README du service](../README.md), § *Lancement local* / § *Tests*) :

```bash
# profil par défaut : 16 utilisateurs virtuels, 10 s, mélange 40% comptes / 30% historique / 30% virement
python loadtest/loadgen.py

# piloté par volume, 8 concurrents, 2000 requêtes, export JSON
python loadtest/loadgen.py -c 8 -n 2000 --json rapport.json

# porte SLO : échoue (code 2) si p95 > 400 ms ou s'il y a la moindre erreur serveur
python loadtest/loadgen.py -c 32 -d 30 --max-p95-ms 400 --max-error-rate 0.0

# mélange personnalisé : écriture seule (stress des virements) — le --mix définit TOUT le mélange
python loadtest/loadgen.py --mix "write_transaction=1" -c 16 -d 20

# cible live (recette sur la stack réelle) — login sur auth, API sur payment-api (services distincts)
python loadtest/loadgen.py --url http://payment-api:8001 --auth-url http://auth:8002 \
  --users 5 --password "$SEED_PASSWORD" -c 20 -d 60
# derrière un ingress unique qui route /login ET /transactions : une seule --url suffit.
```

### Options principales

| Option | Défaut | Rôle |
|---|---|---|
| `--url URL` | — | API cible live (payment-api) ; sinon in-process |
| `--auth-url URL` | = `--url` | service `auth` pour le login (distinct de payment-api) |
| `-c, --concurrency` | `16` | utilisateurs virtuels simultanés (boucle fermée) |
| `-d, --duration` | `10` s | durée (si ni `-d` ni `-n`) |
| `-n, --requests` | — | nombre total de requêtes (prioritaire sur `--duration`) |
| `--users` | `5` | nombre de comptes `demo01..demoNN` exercés |
| `--mix` | `read_accounts=4,read_transactions=3,write_transaction=3` | poids des actions |
| `--balance` | `10 Mrd` centimes | solde initial/compte (in-process) — assez large pour que les virements d'1 cent n'épuisent jamais le solde |
| `--json FICHIER` | — | écrit le résultat structuré |
| `--max-p95-ms`, `--max-error-rate` | — | portes SLO (code de sortie `2` si dépassées) |
| `--seed` | `1234` | graine aléatoire (reproductibilité) |

## Le profil de charge

Boucle fermée : `--concurrency` coroutines, chacune choisissant à chaque tour une action
pondérée et un utilisateur au hasard, sur les **trois** endpoints métier :

- `GET /api/v1/accounts` — lecture des comptes,
- `GET /api/v1/transactions?limit=50` — historique,
- `POST /api/v1/transactions` — virement d'**1 cent** entre les deux comptes du même
  utilisateur (toujours accepté : `201`).

Une requête est un **échec** si le statut est `>= 500` ou si le transport lève (timeout,
connexion) — statut `0`. Les `4xx` (ex. rate-limit, validation) comptent comme réponses
du service, pas comme pannes. En mode in-process bien dimensionné, on n'attend **que** des
`200` (lectures) et `201` (virements).

## Exemple de sortie

```
==========================================================================
  payment-api — test de charge (in-process)
==========================================================================
  concurrence=8  utilisateurs=5  durée=2.03s  requêtes=400
  débit=197.5 req/s   erreurs=0 (0.00%)
--------------------------------------------------------------------------
  endpoint                req   err     p50     p95     p99     max
  (latences en ms)
  TOTAL                   400     0    25.4   116.1   159.7   213.7
  read_accounts           155     0    16.0    50.6    60.8    76.7
  read_transactions       114     0    51.2   147.5   174.9   179.2
  write_transaction       131     0    27.2    88.7   136.2   213.7
--------------------------------------------------------------------------
  statuts HTTP : {200: 269, 201: 131}
==========================================================================
```

## Tests

Un mini-profil est rejoué par pytest comme n'importe quel test du composant
(`make test` → payment-api) :

```bash
pytest tests/test_loadtest_smoke.py -q
```

Il garantit : 0 erreur serveur, uniquement des statuts métier (`200`/`201`), percentiles
monotones, les trois endpoints exercés, et la porte SLO qui rend bien le code `2`.
