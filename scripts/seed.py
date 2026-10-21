#!/usr/bin/env python3
"""seed.py — peuple la base avec le jeu de données FICTIF de `resilience_db.seed`.

Source de vérité UNIQUE du seed : `libs/python/resilience_db/src/resilience_db/seed.py`
(demo01..demo05, un compte EUR financé 1 000,00 € chacun, mot de passe commun SEED_PASSWORD).
Ce script ne fait que l'appliquer, de deux manières selon le contexte :

  - DB joignable d'ici (DATABASE_URL ou POSTGRES_PASSWORD défini, `resilience_db` installé) :
    migrations Alembic puis seed en direct, dans ce processus ;
  - sinon (cas nominal depuis le PC Hôte : Postgres est sur le réseau interne `data`) :
    délégation à `docker compose exec payment-api python -m resilience_db.seed`.

Idempotent : relançable sans doublon (les utilisateurs existants sont ignorés).
Aucune donnée réelle. Le mot de passe vient de SEED_PASSWORD (SOPS -> .env), jamais du code.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPOSE_FILE = ROOT / "infra" / "compose" / "docker-compose.yml"
SEED_SERVICE = "payment-api"  # conteneur qui embarque resilience_db + l'accès au réseau `data`


def _db_configured(env: dict[str, str]) -> bool:
    return bool(env.get("DATABASE_URL") or env.get("POSTGRES_PASSWORD") or env.get("POSTGRES_PASSWORD_FILE"))


def seed_direct(env: dict[str, str]) -> int:
    """Applique migrations + seed via la lib partagée (processus courant)."""
    from resilience_db.config import make_engine, make_session_factory, read_secret
    from resilience_db.migrate import upgrade
    from resilience_db.seed import DEFAULT_MONTHLY_LIMIT_CENTS, DEFAULT_USERS, seed_demo_data

    password = read_secret("SEED_PASSWORD")
    users = int(env.get("SEED_USERS", DEFAULT_USERS))
    engine = make_engine()
    upgrade(engine)
    with make_session_factory(engine)() as session:
        limit = int(env.get("SEED_MONTHLY_LIMIT_CENTS", DEFAULT_MONTHLY_LIMIT_CENTS))
        created = seed_demo_data(session, password, users=users, monthly_limit_cents=limit)
    print(f"seed: {len(created)} utilisateur(s) créé(s): {', '.join(created) or '-'} "
          f"({users} au total, idempotent)")
    return 0


def seed_via_compose(env: dict[str, str]) -> int:
    """Délègue au conteneur payment-api (seul chemin possible depuis l'hôte : DB non exposée)."""
    if not env.get("SEED_PASSWORD"):
        print("seed: SEED_PASSWORD manquant (make decrypt -> .env) — voir scripts/README.md", file=sys.stderr)
        return 1
    cmd = [
        "docker", "compose", "-f", str(COMPOSE_FILE), "exec", "-T",
        "-e", "SEED_PASSWORD", "-e", "SEED_USERS", "-e", "SEED_MONTHLY_LIMIT_CENTS",
        SEED_SERVICE, "python", "-m", "resilience_db.seed",
    ]
    try:
        defaults = {"SEED_USERS": env.get("SEED_USERS", "5"),
                    "SEED_MONTHLY_LIMIT_CENTS": env.get("SEED_MONTHLY_LIMIT_CENTS", "80000")}
        return subprocess.run(cmd, env={**env, **defaults}).returncode
    except FileNotFoundError:
        print("seed: docker introuvable et DB non configurée (DATABASE_URL / POSTGRES_PASSWORD)", file=sys.stderr)
        return 1


def main() -> int:
    env = dict(os.environ)
    if _db_configured(env):
        try:
            return seed_direct(env)
        except ImportError:
            print("seed: resilience_db non installé ici -> délégation au conteneur", file=sys.stderr)
    return seed_via_compose(env)


if __name__ == "__main__":
    sys.exit(main())
