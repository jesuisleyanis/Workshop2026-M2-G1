"""Plafond mensuel de virement (#46) : consommé du mois et contrôle au virement.

Consommé = virements ACCEPTÉS émis depuis le compte vers un compte d'un AUTRE client, depuis
le 1er du mois UTC (un virement entre ses propres comptes n'entame pas le plafond).
`monthly_limit_cents` NULL = pas de plafond (comptes de service) : rien n'est calculé au
virement, donc aucune requête ajoutée sur les comptes à fort trafic (verify_tx, trafic normal).
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time

from resilience_db.models import Account, Transaction, TransactionStatus, User
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from payment_api.stats import period_bounds


def month_window(now: datetime) -> tuple[datetime, date]:
    start, end = period_bounds("month", now)
    return datetime.combine(start, time.min, tzinfo=UTC), end


def _external_spend(owner_id: int, since: datetime):
    others = select(Account.id).where(Account.user_id != owner_id)
    return (
        Transaction.status == TransactionStatus.CREATED.value,
        Transaction.created_at >= since,
        Transaction.dst_account.in_(others),
    )


def used_cents(session: Session, account: Account, now: datetime) -> int:
    since, _ = month_window(now)
    return int(
        session.scalar(
            select(func.coalesce(func.sum(Transaction.amount_cents), 0)).where(
                Transaction.src_account == account.id, *_external_spend(account.user_id, since)
            )
        )
    )


def limits_for(session: Session, user: User, now: datetime) -> list[dict]:
    since, period_end = month_window(now)
    accounts = session.scalars(
        select(Account).where(Account.user_id == user.id).order_by(Account.id)
    ).all()
    used = dict(
        session.execute(
            select(Transaction.src_account, func.sum(Transaction.amount_cents))
            .where(
                Transaction.src_account.in_([a.id for a in accounts]),
                *_external_spend(user.id, since),
            )
            .group_by(Transaction.src_account)
        ).all()
    )
    out = []
    for a in accounts:
        spent = int(used.get(a.id, 0))
        limit = a.monthly_limit_cents
        out.append(
            {
                "account_id": a.id,
                "monthly_limit_cents": limit,
                "used_cents": spent,
                "remaining_cents": None if limit is None else max(0, limit - spent),
                "period_end": period_end,
            }
        )
    return out
