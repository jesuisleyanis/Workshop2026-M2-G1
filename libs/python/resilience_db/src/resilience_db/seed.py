"""Comptes de test fictifs (idempotent, réutilisable par auth, payment-api, scripts/seed.py).

    SEED_PASSWORD=... python -m resilience_db.seed

Toutes les données sont FICTIVES. Le mot de passe n'est jamais en dur : il est passé
en argument (`seed_demo_data`) ou lu dans SEED_PASSWORD / SEED_PASSWORD_FILE (CLI).
"""

from __future__ import annotations

import os
import sys

from sqlalchemy import select
from sqlalchemy.orm import Session

from resilience_db.config import make_engine, make_session_factory, read_secret
from resilience_db.models import Account, User
from resilience_db.passwords import hash_password

DEFAULT_USERS = 5
DEFAULT_BALANCE_CENTS = 100_000  # 1 000,00 EUR fictifs par compte


def demo_username(n: int) -> str:
    return f"demo{n:02d}"


def seed_demo_data(
    session: Session,
    password: str,
    *,
    users: int = DEFAULT_USERS,
    balance_cents: int = DEFAULT_BALANCE_CENTS,
) -> list[str]:
    """Crée demo01..demoNN avec un compte chacun. Idempotent : ignore les existants.

    Renvoie la liste des usernames créés lors de cet appel.
    """
    created: list[str] = []
    password_hash = hash_password(password)
    for n in range(1, users + 1):
        username = demo_username(n)
        if session.scalar(select(User.id).where(User.username == username)) is not None:
            continue
        user = User(username=username, password_hash=password_hash)
        user.accounts.append(
            Account(
                iban_fake=f"FR76 0000 0000 {n:04d} 0000 0000 000",
                balance_cents=balance_cents,
                currency="EUR",
            )
        )
        session.add(user)
        created.append(username)
    session.commit()
    return created


def main() -> int:
    password = read_secret("SEED_PASSWORD")
    users = int(os.environ.get("SEED_USERS", DEFAULT_USERS))
    engine = make_engine()
    with make_session_factory(engine)() as session:
        created = seed_demo_data(session, password, users=users)
    sys.stdout.write(
        f"seed: {len(created)} utilisateur(s) créé(s): {', '.join(created) or '-'}\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
