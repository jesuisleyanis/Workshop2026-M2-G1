"""Comptes de test fictifs (idempotent, réutilisable par auth, payment-api, scripts/seed.py).

    SEED_PASSWORD=... python -m resilience_db.seed

Toutes les données sont FICTIVES. Le mot de passe n'est jamais en dur : il est passé
en argument (`seed_demo_data`) ou lu dans SEED_PASSWORD / SEED_PASSWORD_FILE (CLI).
"""

from __future__ import annotations

import os
import secrets
import sys

from sqlalchemy import select
from sqlalchemy.orm import Session

from resilience_db.config import make_engine, make_session_factory, read_secret
from resilience_db.models import Account, Beneficiary, User
from resilience_db.passwords import hash_password

DEFAULT_USERS = 5
DEFAULT_BALANCE_CENTS = 100_000  # 1 000,00 EUR fictifs par compte

# Tiers FICTIFS destinataires de virements (#43). Comptes sans mot de passe utilisable : ils
# existent pour être crédités, jamais pour se connecter. Préfixe IBAN 9xxx (≠ demoNN).
PAYEES = (
    ("tiers01", "Léa Martin"),
    ("tiers02", "Boulangerie du Port"),
    ("tiers03", "SCI Horizon — loyer"),
    ("tiers04", "Club de sport Atlas"),
)
DEMO_NAMES = ("Camille Durand", "Nathan Petit", "Inès Moreau", "Lucas Girard", "Chloé Fontaine")


def demo_username(n: int) -> str:
    return f"demo{n:02d}"


def demo_iban(n: int) -> str:
    return f"FR76 0000 0000 {n:04d} 0000 0000 000"


def _demo_name(n: int) -> str:
    return DEMO_NAMES[n - 1] if n <= len(DEMO_NAMES) else f"Client démo {n:02d}"


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
                iban_fake=demo_iban(n),
                balance_cents=balance_cents,
                currency="EUR",
            )
        )
        session.add(user)
        created.append(username)
    session.commit()
    seed_beneficiaries(session, users=users)
    return created


def _ensure_payees(session: Session) -> list[tuple[str, Account]]:
    out = []
    for i, (username, name) in enumerate(PAYEES, start=1):
        user = session.scalar(select(User).where(User.username == username))
        if user is None:
            # Mot de passe aléatoire jeté : compte crédité, jamais connectable.
            user = User(username=username, password_hash=hash_password(secrets.token_urlsafe(32)))
            user.accounts.append(
                Account(iban_fake=f"FR76 0000 0000 9{i:03d} 0000 0000 000", balance_cents=0)
            )
            session.add(user)
            session.flush()
        out.append((name, user.accounts[0]))
    return out


def seed_beneficiaries(session: Session, *, users: int = DEFAULT_USERS) -> int:
    """Chaque demoNN enregistre les autres clients de démo et les tiers fictifs. Idempotent.

    Renvoie le nombre de bénéficiaires créés lors de cet appel.
    """
    payees = _ensure_payees(session)
    demo = []
    for n in range(1, users + 1):
        user = session.scalar(select(User).where(User.username == demo_username(n)))
        if user is not None and user.accounts:
            demo.append((n, user))
    created = 0
    for n, owner in demo:
        targets = [(_demo_name(m), other.accounts[0]) for m, other in demo if m != n]
        # 5 à 8 bénéficiaires : jusqu'à 4 clients de démo, complétés par les tiers.
        for name, account in targets[:4] + payees:
            exists = session.scalar(
                select(Beneficiary.id).where(
                    Beneficiary.owner_user_id == owner.id, Beneficiary.account_id == account.id
                )
            )
            if exists is None:
                session.add(
                    Beneficiary(
                        owner_user_id=owner.id,
                        display_name=name,
                        account_id=account.id,
                        iban_fake=account.iban_fake,
                    )
                )
                created += 1
    session.commit()
    return created


def main() -> int:
    password = read_secret("SEED_PASSWORD")
    users = int(os.environ.get("SEED_USERS", DEFAULT_USERS))
    engine = make_engine()
    with make_session_factory(engine)() as session:
        created = seed_demo_data(session, password, users=users)
    sys.stdout.write(f"seed: {len(created)} utilisateur(s) créé(s): {', '.join(created) or '-'}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
