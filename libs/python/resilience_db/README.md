# resilience_db — schéma PostgreSQL partagé

Paquet installable (comme `resilience_common`) qui porte **l'unique définition** du schéma de données de la plateforme fictive : modèles SQLAlchemy 2.0, configuration de connexion, migrations Alembic versionnées, seed de comptes de test.

## Pourquoi un module partagé (et pas une copie par service) ?

`auth` (écrit `users`/`accounts`) et `payment-api` (lit/écrit `accounts`/`transactions`) restent **déployés séparément** mais partagent **la même base et le même schéma**. Dupliquer les modèles dans chaque service créerait deux sources de vérité qui divergent silencieusement (une colonne ajoutée d'un côté, oubliée de l'autre) — exactement le type de défaut qui casse une démo à 17 h le jeudi. Avec un paquet partagé :

- une seule chaîne de migrations Alembic (pas deux services qui se disputent `alembic_version`) ;
- une seule fonction de hash de mot de passe (le seed, `auth` et les tests utilisent la même) ;
- un seul seed réutilisable par `scripts/seed.py` / `make seed`.

Coût accepté : les Dockerfile des services doivent être construits avec la **racine du dépôt** comme contexte (pour `COPY libs/python/resilience_db`). Le couplage de déploiement est limité à l'installation du paquet ; les services ne partagent aucun code applicatif.

## Contenu

| Module | Rôle |
|---|---|
| `models.py` | `User`, `Account` (CHECK `balance_cents >= 0`), `Transaction` (CHECK `amount_cents > 0`), `TransactionStatus` |
| `config.py` | `build_database_url()`, `make_engine()`, `read_secret()` (`NAME` ou `NAME_FILE`) |
| `migrate.py` | `upgrade(engine)` : Alembic `upgrade head`, **verrou consultatif PostgreSQL** pour que `auth` et `payment-api` puissent démarrer en même temps |
| `migrations/` | `versions/0001_initial_schema.py` |
| `passwords.py` | bcrypt via passlib (coût 12), refus > 72 octets, hash factice anti-énumération |
| `seed.py` | `seed_demo_data(session, password)` idempotent ; CLI `python -m resilience_db.seed` |
| `factories.py` | `new_fake_iban()` (IBAN fictif, non valide mod-97) |

## Schéma

```
users(id PK, username UNIQUE, password_hash, created_at)
accounts(id PK, user_id FK users, iban_fake UNIQUE, balance_cents BIGINT CHECK >= 0, currency)
transactions(id PK, src_account FK accounts, dst_account FK accounts,
             amount_cents BIGINT CHECK > 0, status ['created'|'rejected'], created_at, request_id)
```

Les montants sont des **entiers en centimes** (jamais de flottant).

## Configuration de connexion

| Variable | Défaut | Rôle |
|---|---|---|
| `POSTGRES_HOST` | `postgres` | hôte |
| `POSTGRES_PORT` | `5432` | port |
| `POSTGRES_DB` | `resilience` | base |
| `POSTGRES_USER` | `resilience` | utilisateur |
| `POSTGRES_PASSWORD` / `POSTGRES_PASSWORD_FILE` | — (obligatoire) | mot de passe, **jamais en dur** |
| `DATABASE_URL` | — | surcharge complète (utilisée par les tests : `sqlite://`) |

Pilote : `psycopg` 3 (`postgresql+psycopg://`).

## Utilisation

```bash
pip install -e libs/python/resilience_db            # (après resilience_common)
python -m resilience_db.migrate                      # applique les migrations
SEED_PASSWORD='...' python -m resilience_db.seed     # demo01..demo05 (1 000,00 EUR fictifs chacun)
```

Les services appellent eux-mêmes `upgrade()` au démarrage (`RUN_MIGRATIONS=true`, défaut). Nouvelle migration : `cd libs/python/resilience_db && DATABASE_URL=sqlite:///dev.db alembic -c alembic.ini revision -m "..."`.

## Tests

```bash
pip install -e "libs/python/resilience_db[test]" && pytest libs/python/resilience_db
```

SQLite (en mémoire / fichier temporaire) : vérifie que les migrations produisent le même schéma que les modèles, l'idempotence, le seed, la config sans secret en dur.
