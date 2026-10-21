"""Virements programmés (#48) : règles des échéances + exécuteur idempotent.

Idempotence : pour chaque échéance, la ligne `scheduled_runs(scheduled_id, run_on)` (UNIQUE) est
réservée DANS LA MÊME TRANSACTION que l'avancement de `next_run_on`, puis le virement passe par
`ledger.transfer` (mêmes règles : solde, plafond). Deux répliques de payment-api, ou un
redémarrage par la remédiation, ne peuvent donc jamais exécuter deux fois la même échéance : la
seconde réservation échoue sur la contrainte. Un arrêt brutal entre réservation et virement laisse
la ligne en `pending` (au plus une fois, jamais deux), visible à l'écran.
"""

from __future__ import annotations

import calendar
import logging
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta

from resilience_common.metrics import transactions_total
from resilience_db.models import Account, ScheduledRun, ScheduledTransfer, User
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from payment_api.ledger import MAX_AMOUNT_CENTS, Rejection, transfer
from payment_api.observability import log_event

MAX_ACTIVE_PER_USER = 20
MAX_HORIZON = timedelta(days=366)
MAX_CATCH_UP = 31  # échéances rattrapées au plus par programmation et par passage


def _add_month(anchor_day: int, d: date) -> date:
    year, month = (d.year + 1, 1) if d.month == 12 else (d.year, d.month + 1)
    return date(year, month, min(anchor_day, calendar.monthrange(year, month)[1]))


def following(s: ScheduledTransfer, current: date) -> date | None:
    """Échéance suivant `current`, ou None si la programmation est terminée.

    Mensuel : ancré sur le jour de `start_on` (un 31 donne 30 en avril, 28/29 en février, puis
    revient au 31) ; hebdomadaire : +7 jours ; une fois : rien après.
    """
    if s.frequency == "once":
        return None
    nxt = (
        current + timedelta(days=7)
        if s.frequency == "weekly"
        else _add_month(s.start_on.day, current)
    )
    return None if s.end_on is not None and nxt > s.end_on else nxt


# ------------------------------------------------------------------------------ API métier
def create(session: Session, user: User, body, today: date) -> ScheduledTransfer:
    if body.amount_cents <= 0:
        raise Rejection(422, "invalid_amount", "Amount must be strictly positive")
    if body.amount_cents > MAX_AMOUNT_CENTS:
        raise Rejection(422, "amount_too_large", "Amount exceeds the maximum allowed")
    if body.src_account == body.dst_account:
        raise Rejection(422, "same_account", "Source and destination must differ")
    if not today <= body.start_on <= today + MAX_HORIZON or (
        body.end_on is not None and body.end_on < body.start_on
    ):
        raise Rejection(422, "invalid_dates", "start_on must be within a year, end_on after it")
    src = session.get(Account, body.src_account)
    if src is None or src.user_id != user.id:
        raise Rejection(404, "account_not_found", "Source account not found")
    if session.get(Account, body.dst_account) is None:
        raise Rejection(404, "destination_not_found", "Destination account not found")
    active = session.scalars(
        select(ScheduledTransfer.id).where(
            ScheduledTransfer.owner_user_id == user.id,
            ScheduledTransfer.status.in_(("active", "paused")),
        )
    ).all()
    if len(active) >= MAX_ACTIVE_PER_USER:
        raise Rejection(409, "schedule_limit", "Too many scheduled transfers")
    s = ScheduledTransfer(
        owner_user_id=user.id,
        src_account=body.src_account,
        dst_account=body.dst_account,
        amount_cents=body.amount_cents,
        category=body.category,
        frequency=body.frequency,
        start_on=body.start_on,
        next_run_on=body.start_on,
        end_on=body.end_on,
        status="active",
    )
    session.add(s)
    session.commit()
    return s


def owned(session: Session, user: User, schedule_id: int) -> ScheduledTransfer:
    s = session.get(ScheduledTransfer, schedule_id, with_for_update=True)
    if s is None or s.owner_user_id != user.id:
        raise Rejection(404, "schedule_not_found", "Scheduled transfer not found")
    return s


def set_status(session: Session, user: User, schedule_id: int, status: str) -> ScheduledTransfer:
    s = owned(session, user, schedule_id)
    if s.status in ("cancelled", "completed"):
        raise Rejection(409, "schedule_closed", "This scheduled transfer is closed")
    s.status = status
    session.commit()
    return s


def cancel(session: Session, user: User, schedule_id: int) -> None:
    s = owned(session, user, schedule_id)
    if s.status != "completed":
        s.status, s.next_run_on = "cancelled", None
    session.commit()


def list_for(session: Session, user: User) -> list[tuple[ScheduledTransfer, ScheduledRun | None]]:
    rows = session.scalars(
        select(ScheduledTransfer)
        .where(ScheduledTransfer.owner_user_id == user.id)
        .order_by(ScheduledTransfer.id.desc())
    ).all()
    last = {}
    if rows:
        for run in session.scalars(
            select(ScheduledRun)
            .where(ScheduledRun.scheduled_id.in_([s.id for s in rows]))
            .order_by(ScheduledRun.run_on, ScheduledRun.id)
        ):
            last[run.scheduled_id] = run  # le dernier par date l'emporte
    return [(s, last.get(s.id)) for s in rows]


# ------------------------------------------------------------------------------ exécuteur
def _claim(session: Session, schedule_id: int, today: date) -> tuple[ScheduledRun, int] | None:
    """Réserve l'échéance due et avance la programmation, atomiquement. None si rien à faire
    (ou déjà réservée par une autre réplique : la contrainte UNIQUE tranche)."""
    s = session.get(ScheduledTransfer, schedule_id)
    if s is None or s.status != "active" or s.next_run_on is None or s.next_run_on > today:
        return None
    run = ScheduledRun(scheduled_id=s.id, run_on=s.next_run_on, status="pending")
    session.add(run)
    nxt = following(s, s.next_run_on)
    s.next_run_on = nxt
    if nxt is None:
        s.status = "completed"
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        return None
    return run, s.owner_user_id


def run_due(
    session_factory: Callable[[], Session],
    log: logging.Logger,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> int:
    """Exécute les échéances dues (aujourd'hui UTC inclus). Renvoie le nombre d'exécutions."""
    today = now().astimezone(UTC).date()
    done = 0
    with session_factory() as session:
        due = session.scalars(
            select(ScheduledTransfer.id).where(
                ScheduledTransfer.status == "active", ScheduledTransfer.next_run_on <= today
            )
        ).all()
    for schedule_id in due:
        for _ in range(MAX_CATCH_UP):
            with session_factory() as session:
                claimed = _claim(session, schedule_id, today)
                if claimed is None:
                    break
                run, owner_id = claimed
                _execute(session, run, owner_id, log, now)
                done += 1
    return done


def _execute(session: Session, run: ScheduledRun, owner_id: int, log, now) -> None:
    s = session.get(ScheduledTransfer, run.scheduled_id)
    owner = session.get(User, owner_id)
    try:
        tx = transfer(
            session,
            owner,
            s.src_account,
            s.dst_account,
            s.amount_cents,
            f"sched-{s.id}-{run.run_on.isoformat()}",
            s.category,
            now(),
        )
    except Rejection as rej:
        session.rollback()
        run = session.get(ScheduledRun, run.id)
        run.status, run.error_code = "failed", rej.code
        session.commit()
        transactions_total.labels(result="rejected").inc()
        log_event(
            log,
            logging.WARNING,
            "scheduled_transfer_failed",
            f"Scheduled transfer {s.id} run {run.run_on} failed ({rej.code})",
            user=owner.username,
        )
        return
    run = session.get(ScheduledRun, run.id)
    run.status, run.transaction_id = "executed", tx.id
    session.commit()
    transactions_total.labels(result="created").inc()
    log_event(
        log,
        logging.INFO,
        "scheduled_transfer_executed",
        f"Scheduled transfer {s.id} run {run.run_on} executed (transaction {tx.id})",
        user=owner.username,
    )
