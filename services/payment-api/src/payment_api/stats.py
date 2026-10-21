"""Agrégats de dépenses (#44) : `GET /api/v1/stats/spending?period=week|month&offset=0`.

Dépense = virement ACCEPTÉ d'un compte du client vers un compte qui n'est pas à lui (un
virement entre ses propres comptes n'est pas une dépense ; un refus non plus). Périodes en
UTC : semaine ISO (lundi -> lundi) ou mois civil, bornes [start, end) ; `offset` <= 0 recule
d'autant de périodes. Agrégation en SQL (GROUP BY) : coût borné quel que soit l'historique.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta

from resilience_db.models import Account, Transaction, TransactionStatus, User
from sqlalchemy import func, select
from sqlalchemy.orm import Session


def period_bounds(period: str, now: datetime, offset: int = 0) -> tuple[date, date]:
    today = now.astimezone(UTC).date()
    if period == "week":
        start = today - timedelta(days=today.weekday()) + timedelta(weeks=offset)
        return start, start + timedelta(days=7)
    month = today.year * 12 + today.month - 1 + offset
    start = date(month // 12, month % 12 + 1, 1)
    end = (start + timedelta(days=32)).replace(day=1)
    return start, end


def spend_scope(owner_id: int, since: datetime, until: datetime) -> tuple:
    """Filtre « dépense » partagé par les stats (#44) et le plafond (#46) : virement accepté vers
    un compte qui n'est pas au client, dans [since, until). La source est filtrée par l'appelant."""
    own = select(Account.id).where(Account.user_id == owner_id)
    return (
        Transaction.dst_account.not_in(own),
        Transaction.status == TransactionStatus.CREATED.value,
        Transaction.created_at >= since,
        Transaction.created_at < until,
    )


def _utc_day(session: Session, column):
    # Jour calendaire UTC calculé en base. PostgreSQL : timestamptz ramené en UTC quel que soit
    # le fuseau de session ; SQLite stocke déjà l'UTC sous forme de texte.
    if session.get_bind().dialect.name == "postgresql":
        return func.date(func.timezone("UTC", column))
    return func.date(column)


def spending(session: Session, user: User, period: str, now: datetime, offset: int = 0) -> dict:
    start, end = period_bounds(period, now, offset)
    own = select(Account.id).where(Account.user_id == user.id)
    scope = (
        Transaction.src_account.in_(own),
        *spend_scope(
            user.id,
            datetime.combine(start, time.min, tzinfo=UTC),
            datetime.combine(end, time.min, tzinfo=UTC),
        ),
    )
    total_col = func.sum(Transaction.amount_cents)
    by_category = session.execute(
        select(Transaction.category, total_col).where(*scope).group_by(Transaction.category)
    ).all()
    day = _utc_day(session, Transaction.created_at)
    by_day = {
        str(d): int(a)
        for d, a in session.execute(select(day, total_col).where(*scope).group_by(day)).all()
    }
    total = sum(int(a) for _, a in by_category)
    days = [start + timedelta(days=i) for i in range((end - start).days)]
    return {
        "period": period,
        "offset": offset,
        "start": start,
        "end": end,
        "total_cents": total,
        "by_category": [
            {"category": c, "amount_cents": int(a), "share": round(int(a) / total, 4)}
            for c, a in sorted(by_category, key=lambda kv: (-int(kv[1]), kv[0]))
        ],
        "by_day": [{"date": d, "amount_cents": by_day.get(d.isoformat(), 0)} for d in days],
    }
