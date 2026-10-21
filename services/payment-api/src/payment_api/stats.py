"""Agrégats de dépenses (#44) : `GET /api/v1/stats/spending?period=week|month`.

Dépense = virement ACCEPTÉ d'un compte du client vers un compte qui n'est pas à lui (un
virement entre ses propres comptes n'est pas une dépense ; un refus non plus). Périodes en
UTC : semaine ISO courante (lundi -> lundi) ou mois civil courant, bornes [start, end).
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, date, datetime, time, timedelta

from resilience_db.models import Account, Transaction, TransactionStatus, User
from sqlalchemy import select
from sqlalchemy.orm import Session


def period_bounds(period: str, now: datetime) -> tuple[date, date]:
    today = now.astimezone(UTC).date()
    if period == "week":
        start = today - timedelta(days=today.weekday())
        return start, start + timedelta(days=7)
    start = today.replace(day=1)
    end = (start + timedelta(days=32)).replace(day=1)
    return start, end


def _utc_day(ts: datetime) -> date:
    # SQLite relit des datetimes naïfs (stockés en UTC) ; PostgreSQL les renvoie avec fuseau.
    return (ts if ts.tzinfo else ts.replace(tzinfo=UTC)).astimezone(UTC).date()


def spending(session: Session, user: User, period: str, now: datetime) -> dict:
    start, end = period_bounds(period, now)
    lo = datetime.combine(start, time.min, tzinfo=UTC)
    hi = datetime.combine(end, time.min, tzinfo=UTC)
    own = select(Account.id).where(Account.user_id == user.id)
    rows = session.execute(
        select(Transaction.category, Transaction.amount_cents, Transaction.created_at).where(
            Transaction.src_account.in_(own),
            Transaction.dst_account.not_in(own),
            Transaction.status == TransactionStatus.CREATED.value,
            Transaction.created_at >= lo,
            Transaction.created_at < hi,
        )
    ).all()

    by_category: dict[str, int] = defaultdict(int)
    by_day: dict[date, int] = defaultdict(int)
    for category, amount, created_at in rows:
        by_category[category] += amount
        by_day[_utc_day(created_at)] += amount
    total = sum(by_category.values())
    days = [start + timedelta(days=i) for i in range((end - start).days)]
    return {
        "period": period,
        "start": start,
        "end": end,
        "total_cents": total,
        "by_category": [
            {"category": c, "amount_cents": a, "share": round(a / total, 4)}
            for c, a in sorted(by_category.items(), key=lambda kv: (-kv[1], kv[0]))
        ],
        "by_day": [{"date": d, "amount_cents": by_day.get(d, 0)} for d in days],
    }
