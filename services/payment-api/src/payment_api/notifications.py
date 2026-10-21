"""Notifications in-app (#49) : génération sur les événements métier, lecture, rétention.

Écrites DANS LA TRANSACTION de l'événement (`session.add`, sans flush ni commit ici) : aucune
notification sans virement, aucun virement sans notification. Chemin chaud (le trafic normal
fait ~1 virement/s sur les comptes de service) : deux lignes de plus dans le commit du virement,
rien d'autre. La rétention (RETENTION par client) est appliquée hors chemin chaud : par la tâche
de fond périodique (`prune_all`) et à la lecture (`list_for`).
"""

from __future__ import annotations

from datetime import UTC, datetime

from resilience_db.models import NOTIFICATION_TYPES, Notification
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

RETENTION = 100


def euros(cents: int) -> str:
    return f"{cents / 100:,.2f}".replace(",", "\u202f").replace(".", ",") + "\u00a0€"


def notify(session: Session, user_id: int, type_: str, title: str, body: str) -> None:
    if type_ not in NOTIFICATION_TYPES:  # erreur de programmation : jamais en base (CHECK)
        raise ValueError(f"unknown notification type {type_!r}")
    session.add(Notification(user_id=user_id, type=type_, title=title[:80], body=body[:200]))


def prune(session: Session, user_id: int) -> None:
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


def prune_all(session: Session) -> None:
    """Passe de rétention (tâche de fond) : seulement les clients au-delà de RETENTION."""
    over = session.scalars(
        select(Notification.user_id)
        .group_by(Notification.user_id)
        .having(func.count(Notification.id) > RETENTION)
    ).all()
    for user_id in over:
        prune(session, user_id)
    session.commit()


def list_for(session: Session, user_id: int, unread: bool) -> list[Notification]:
    prune(session, user_id)
    session.commit()
    q = select(Notification).where(Notification.user_id == user_id)
    if unread:
        q = q.where(Notification.read_at.is_(None))
    return list(session.scalars(q.order_by(Notification.id.desc()).limit(RETENTION)))


def unread_count(session: Session, user_id: int) -> int:
    return session.scalar(
        select(func.count(Notification.id)).where(
            Notification.user_id == user_id, Notification.read_at.is_(None)
        )
    )


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
