"""Comptes de test fictifs (idempotent, réutilisable par auth, payment-api, scripts/seed.py).

    SEED_PASSWORD=... python -m resilience_db.seed

Toutes les données sont FICTIVES. Le mot de passe n'est jamais en dur : il est passé
en argument (`seed_demo_data`) ou lu dans SEED_PASSWORD / SEED_PASSWORD_FILE (CLI).
"""

from __future__ import annotations

import os
import secrets
import sys
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from resilience_db.config import make_engine, make_session_factory, read_secret
from resilience_db.models import Account, Beneficiary, Transaction, User
from resilience_db.passwords import hash_password

DEFAULT_USERS = 5
DEFAULT_BALANCE_CENTS = 100_000  # 1 000,00 EUR fictifs par compte
# Plafond mensuel (#46) des clients de démo « humains ». demo01/demo02 sont des comptes de
# SERVICE (verify_tx, trafic normal, service_flood) : jamais plafonnés, sinon la vérification
# de reprise et la baseline ML (ratio 4xx) casseraient après quelques heures de trafic.
# Sous le solde (1 000 €) : le plafond se voit et se déclenche avant le solde insuffisant.
DEFAULT_MONTHLY_LIMIT_CENTS = 80_000  # 800,00 EUR
SERVICE_USERS = frozenset({"demo01", "demo02"})

# Tiers FICTIFS destinataires de virements (#43). Comptes sans mot de passe utilisable : ils
# existent pour être crédités, jamais pour se connecter. Banque fictive « 9999 » : espace
# d'IBAN disjoint de demo_iban (« 0000 »), quel que soit SEED_USERS.
PAYEES = (
    ("tiers01", "Léa Martin"),
    ("tiers02", "Boulangerie du Port"),
    ("tiers03", "SCI Horizon — loyer"),
    ("tiers04", "Club de sport Atlas"),
)
# Historique de dépenses catégorisées (#44) : (index du tiers, catégorie, centimes). Placé
# dans la semaine et le mois COURANTS au moment du seed (cf. seed_history), pour que l'écran
# Statistiques ne soit jamais vide en démo, même si `make seed` est rejoué le 1er du mois.
HISTORY = (
    (1, "food", 1250),
    (0, "leisure", 2400),
    (1, "food", 860),
    (3, "subscriptions", 2999),
    (1, "shopping", 4590),
    (0, "transport", 1800),
    (3, "health", 2500),
    (2, "housing", 5000),
)
WEEK_ENTRIES = 3  # les 3 premières tombent dans la semaine ISO courante
DEMO_NAMES = ("Camille Durand", "Nathan Petit", "Inès Moreau", "Lucas Girard", "Chloé Fontaine")


def demo_username(n: int) -> str:
    return f"demo{n:02d}"


def demo_iban(n: int) -> str:
    return f"FR76 0000 0000 {n:04d} 0000 0000 000"


def _backfill_limits(session: Session, users: int, limit: int) -> None:
    """Clients de démo seedés avant #46 (colonne NULL après la migration) : plafond posé une fois.
    Les comptes de service et un plafond déjà fixé ne sont jamais touchés."""
    for n in range(1, users + 1):
        username = demo_username(n)
        if username in SERVICE_USERS:
            continue
        user = session.scalar(select(User).where(User.username == username))
        for account in user.accounts if user else []:
            if account.monthly_limit_cents is None:
                account.monthly_limit_cents = limit
    session.commit()


def payee_iban(i: int) -> str:
    return f"FR76 9999 0000 {i:04d} 0000 0000 000"


def _demo_name(n: int) -> str:
    return DEMO_NAMES[n - 1] if n <= len(DEMO_NAMES) else f"Client démo {n:02d}"


def seed_demo_data(
    session: Session,
    password: str,
    *,
    users: int = DEFAULT_USERS,
    balance_cents: int = DEFAULT_BALANCE_CENTS,
    monthly_limit_cents: int = DEFAULT_MONTHLY_LIMIT_CENTS,
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
                monthly_limit_cents=None if username in SERVICE_USERS else monthly_limit_cents,
            )
        )
        session.add(user)
        created.append(username)
    session.commit()
    _backfill_limits(session, users, monthly_limit_cents)
    seed_beneficiaries(session, users=users)
    seed_history(session, [demo_username(n) for n in range(1, users + 1)])
    return created


def _history_dates(now: datetime) -> list[datetime]:
    """Dates réparties entre le début de la période et `now` (jamais dans le futur)."""
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    week_start = (now - timedelta(days=now.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    recent_from = max(month_start, week_start)
    dates = []
    for i in range(len(HISTORY)):
        lo, n, k = (
            (recent_from, WEEK_ENTRIES, i)
            if i < WEEK_ENTRIES
            else (month_start, len(HISTORY) - WEEK_ENTRIES, i - WEEK_ENTRIES)
        )
        dates.append(now - (now - lo) * (k + 1) / (n + 1))
    return dates


def seed_history(session: Session, usernames: list[str], now: datetime | None = None) -> int:
    """Dépenses vers les tiers fictifs pour chaque client SANS dépense dans le mois courant.

    Idempotent à l'échelle du mois : rejouer `make seed` (ou `attacks/reset.sh`) avant la démo
    remplit le mois en cours une seule fois. Le solde du client reste celui du seed ; les tiers
    sont crédités. `usernames` : clients concernés (tous les demoNN du seed).
    """
    now = now or datetime.now(UTC)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    payees = [account for _, account in _ensure_payees(session)]
    payee_ids = [a.id for a in payees]
    count = 0
    for username in usernames:
        user = session.scalar(select(User).where(User.username == username))
        if user is None or not user.accounts:
            continue
        src = user.accounts[0]
        already = session.scalar(
            select(Transaction.id).where(
                Transaction.src_account == src.id,
                Transaction.dst_account.in_(payee_ids),
                Transaction.created_at >= month_start,
            )
        )
        if already is not None:
            continue
        for (payee, category, amount), at in zip(HISTORY, _history_dates(now), strict=True):
            dst = payees[payee % len(payees)]
            dst.balance_cents += amount
            session.add(
                Transaction(
                    src_account=src.id,
                    dst_account=dst.id,
                    amount_cents=amount,
                    status="created",
                    category=category,
                    created_at=at,
                )
            )
            count += 1
    session.commit()
    return count


def _ensure_payees(session: Session) -> list[tuple[str, Account]]:
    out = []
    for i, (username, name) in enumerate(PAYEES, start=1):
        user = session.scalar(select(User).where(User.username == username))
        if user is None:
            # Mot de passe aléatoire jeté : compte crédité, jamais connectable.
            user = User(username=username, password_hash=hash_password(secrets.token_urlsafe(32)))
            session.add(user)
        if not user.accounts:
            user.accounts.append(Account(iban_fake=payee_iban(i), balance_cents=0))
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
    limit = int(os.environ.get("SEED_MONTHLY_LIMIT_CENTS", DEFAULT_MONTHLY_LIMIT_CENTS))
    engine = make_engine()
    with make_session_factory(engine)() as session:
        created = seed_demo_data(session, password, users=users, monthly_limit_cents=limit)
    sys.stdout.write(f"seed: {len(created)} utilisateur(s) créé(s): {', '.join(created) or '-'}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
