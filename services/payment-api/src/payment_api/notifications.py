"""Notifications in-app (#49) : génération sur les événements métier, lecture, rétention.

Écrites DANS LA TRANSACTION de l'événement (pas de commit ici) : aucune notification sans
virement, aucun virement sans notification. Chemin chaud (le trafic normal fait ~1 virement/s
sur les comptes de service) : un INSERT, et la purge de rétention n'a lieu qu'une fois sur
PRUNE_EVERY insertions, sur l'index (user_id, id) — coût borné, rétention ~RETENTION.
"""

from __future__ import annotations

from datetime import UTC, datetime

from resilience_db.models import Notification
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

RETENTION = 100
PRUNE_EVERY = 20


def euros(cents: int) -> str:
    return f"{cents / 100:,.2f}".replace(",", "\u202f").replace(".", ",") + "\u00a0€"


def notify(session: Session, user_id: int, type_: str, title: str, body: str) -> None:
    n = Notification(user_id=user_id, type=type_, title=title[:80], body=body[:200])
    session.add(n)
    session.flush()
    if n.id % PRUNE_EVERY == 0:
        _prune(session, user_id)


def _prune(session: Session, user_id: int) -> None:
    cutoff = session.scalar(
        select(Notification.id)
        .where(Notification.user_id == user_id)
        .order_by(Notification.id.desc())
        .offset(RETENTION)
        .limit(1)
    )
    if cutoff is not None:
        session.execute(
            delete(Notification).where(Notification.user_id == user_id, Notification.id <= cutoff)
        )


def list_for(session: Session, user_id: int, unread: bool) -> list[Notification]:
    q = select(Notification).where(Notification.user_id == user_id)
    if unread:
        q = q.where(Notification.read_at.is_(None))
    return list(session.scalars(q.order_by(Notification.id.desc()).limit(RETENTION)))


def mark_read(session: Session, user_id: int, notification_id: int) -> Notification | None:
    n = session.get(Notification, notification_id)
    if n is None or n.user_id != user_id:
        return None
    if n.read_at is None:
        n.read_at = datetime.now(UTC)
        session.commit()
    return n


def mark_all_read(session: Session, user_id: int) -> int:
    result = session.execute(
        update(Notification)
        .where(Notification.user_id == user_id, Notification.read_at.is_(None))
        .values(read_at=datetime.now(UTC))
    )
    session.commit()
    return result.rowcount or 0
