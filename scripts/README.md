# scripts/ — outillage transverse de la démo

| Script | Rôle | Commande |
|---|---|---|
| `decrypt-secrets.sh` | SOPS/age → `.env` (non commité) | `make decrypt` |
| `seed.py` | applique le jeu de données fictif | `make seed` |
| `verify_tx` | **transaction de contrôle** (preuve de reprise), exit `0` = OK / `1` = KO | `make verify` |
| `demo.sh` | les 5 temps de la démo enchaînés | `make demo SC=<scenario>` |
| `package_deliverables.sh` | `Workshop2026-M2-G1-Code.zip` sans secrets : audit → zip (exclusions : `.git`, deps, `dist`/caches/`egg-info`, dumps, journaux, `.env`/clés, autres livrables) → re-scan noms + contenu (clé age / clé privée ⇒ abandon). Testé sur un faux dépôt (`tests/test_package_deliverables.py`) | `make package` |

Les cibles `make seed`, `make verify` et `make demo` chargent `.env` (produit par `make decrypt`)
pour disposer de `SEED_PASSWORD`.

## Jeu de données fictif (source de vérité unique)

Défini **une seule fois** dans `libs/python/resilience_db/src/resilience_db/seed.py` ; `scripts/seed.py`
ne fait que l'appliquer. Toutes les données sont fictives.

| Utilisateur | Mot de passe | Compte | Solde initial |
|---|---|---|---|
| `demo01` … `demo05` | `SEED_PASSWORD` (commun, SOPS → `.env`) | 1 compte EUR chacun, IBAN fictif `FR76 0000 0000 000N 0000 0000 000` | **1 000,00 €** (100 000 centimes) |

| `tiers01` … `tiers04` | aléatoire, jeté (**non connectables**) | 1 compte EUR chacun, IBAN `FR76 9999 0000 000N 0000 0000 000` (tiers fictifs : Léa Martin, Boulangerie du Port…) | 0 € |

Chaque `demoNN` a **5 à 8 bénéficiaires** (#43) : jusqu'à 4 autres clients de démo + les 4 tiers,
et **8 dépenses catégorisées** vers les tiers, placées dans la semaine et le mois **en cours** au moment
du seed (#44 : écran Statistiques jamais vide ; un `make seed` / `reset.sh` avant la démo suffit, une fois
par mois). Le solde affiché reste 1 000,00 € (`verify_tx` inchangé).

- Plafond mensuel (#46) : `demo03`+ plafonnés à `SEED_MONTHLY_LIMIT_CENTS` (défaut 80 000 = 800 €, sous le solde : le plafond se voit et se déclenche ; transmis aussi au conteneur ; un client seedé avant #46 est rattrapé) ;
  `demo01`/`demo02` (comptes de service : `verify_tx`, trafic normal, `service_flood`) **sans plafond**.
- Idempotent : les utilisateurs et bénéficiaires existants sont ignorés, relançable sans doublon.
- `SEED_USERS` (défaut `5`) change le nombre de comptes.

### `seed.py` : deux modes, un seul seed

| Contexte | Comportement |
|---|---|
| Depuis le PC Hôte (cas nominal : Postgres n'est joignable que sur le réseau interne `data`) | délègue à `docker compose exec payment-api python -m resilience_db.seed` (le conteneur embarque `resilience_db` et l'accès DB) |
| `DATABASE_URL` ou `POSTGRES_PASSWORD` défini et `resilience_db` installé (conteneur, dev, tests) | migrations Alembic puis seed **en direct** |

Les anciens comptes `demo-pass-0N` / `FR-FAKE-000N` (chemin API `register`, comptes **non financés**)
ont été supprimés : `register` d'`auth` n'accepte que `username` + `password` et ouvre un compte au solde
`REGISTER_INITIAL_BALANCE_CENTS` (0 par défaut).

## `verify_tx` — contrat

Transaction fictive de bout en bout, **à travers le WAF** comme un vrai client. C'est la preuve
rejouée par `make demo` (temps 1 et 5) et par la boucle `verify` du moteur de remédiation.

Étapes : login `VERIFY_USER` → `GET /api/v1/accounts` (id entier du compte source) → résolution du
compte destinataire → `POST /api/v1/transactions {src_account, dst_account, amount_cents}` (schéma
`TransactionIn` de payment-api : **trois entiers**, montants en centimes) → la transaction créée doit
figurer dans `GET /api/v1/transactions`.

| Variable | Défaut | Rôle |
|---|---|---|
| `BASE_URL` | `https://localhost` | point d'entrée WAF (`https://waf` depuis le conteneur remediation) |
| `VERIFY_USER` | `demo01` | compte source (seedé, financé) |
| `VERIFY_PASSWORD` | `SEED_PASSWORD` | mot de passe ; **obligatoire** (l'un des deux), jamais en dur |
| `VERIFY_DST_USER` | `demo02` | destinataire : son premier compte est résolu via un second login |
| `VERIFY_DST_ACCOUNT` | — | id entier du compte destinataire : court-circuite la résolution |
| `VERIFY_AMOUNT_CENTS` | `100` | montant (1,00 €) |
| `VERIFY_TIMEOUT` | `5` | timeout par requête (s) |

Sortie : `0` et une ligne `verify_tx: OK — transaction fictive <id> créée (...)` ; sinon `1` et la cause
sur stderr (`service injoignable`, `transaction refusée (HTTP 409) — insufficient_funds: ...`, login KO,
historique incohérent). Aucune 422 n'est attendue en fonctionnement nominal.

## Tests

```bash
python -m pytest -q scripts/tests     # inclus dans `make test`
```

- `test_verify_tx.py` : corps de requête conforme au contrat, sortie 0/1 selon chaque cas (fonds
  insuffisants, identifiants invalides, service injoignable, historique), lecture de l'environnement.
- `test_seed.py` : seed direct sur SQLite (5 comptes financés, idempotent) et délégation Compose.
