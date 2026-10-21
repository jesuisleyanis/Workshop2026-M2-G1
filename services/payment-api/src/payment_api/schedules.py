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
import contextlib
import logging
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta

from resilience_common.metrics import transactions_total
from resilience_db.models import Account, ScheduledRun, ScheduledTransfer, User
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from payment_api.ledger import Rejection, check_amount_and_accounts, transfer
from payment_api.notifications import euros, notify
from payment_api.observability import log_event

MAX_ACTIVE_PER_USER = 20
MAX_HORIZON = timedelta(days=366)
MAX_CATCH_UP = 31  # échéances exécutées au plus par programmation et par passage
CATCH_UP_WINDOW = timedelta(days=31)  # une échéance plus ancienne est sautée, jamais débitée


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
    check_amount_and_accounts(body.src_account, body.dst_account, body.amount_cents)
    if not today <= body.start_on <= today + MAX_HORIZON or (
        body.end_on is not None and body.end_on < body.start_on
    ):
        raise Rejection(422, "invalid_dates", "start_on must be within a year, end_on after it")
    src = session.get(Account, body.src_account)
    if src is None or src.user_id != user.id:
        raise Rejection(404, "account_not_found", "Source account not found")
    if session.get(Account, body.dst_account) is None:
        raise Rejection(404, "destination_not_found", "Destination account not found")
    active = session.scalar(
        select(func.count(ScheduledTransfer.id)).where(
            ScheduledTransfer.owner_user_id == user.id,
            ScheduledTransfer.status.in_(("active", "paused")),
        )
    )
    if active >= MAX_ACTIVE_PER_USER:
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


def _first_on_or_after(s: ScheduledTransfer, day: date) -> date | None:
    current = s.next_run_on
    while current is not None and current < day:
        current = following(s, current)
    return current


def set_status(
    session: Session, user: User, schedule_id: int, status: str, today: date
) -> ScheduledTransfer:
    s = owned(session, user, schedule_id)
    if s.status in ("cancelled", "completed"):
        raise Rejection(409, "schedule_closed", "This scheduled transfer is closed")
    if status == "active" and s.status == "paused":
        # Reprise : seules les échéances À VENIR comptent, jamais celles manquées pendant la pause.
        s.next_run_on = _first_on_or_after(s, today)
        if s.next_run_on is None:
            status = "completed"
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
        # Une ligne par programmation (la dernière exécution), pas tout l'historique.
        latest = (
            select(func.max(ScheduledRun.id))
            .where(ScheduledRun.scheduled_id.in_([s.id for s in rows]))
            .group_by(ScheduledRun.scheduled_id)
        )
        for run in session.scalars(select(ScheduledRun).where(ScheduledRun.id.in_(latest))):
            last[run.scheduled_id] = run
    return [(s, last.get(s.id)) for s in rows]


# ------------------------------------------------------------------------------ exécuteur
def _claim(session: Session, schedule_id: int, today: date) -> tuple[ScheduledRun, int] | None:
    """Réserve l'échéance due et avance la programmation, atomiquement. None si rien à faire
    (ou déjà réservée par une autre réplique : la contrainte UNIQUE tranche)."""
    # Verrou de ligne : une annulation ou une pause concurrente ne peut pas être écrasée.
    s = session.get(ScheduledTransfer, schedule_id, with_for_update=True)
    if s is None or s.status != "active" or s.next_run_on is None or s.next_run_on > today:
        session.rollback()
        return None
    stale = today - CATCH_UP_WINDOW
    if s.next_run_on < stale:  # arrêt très long : on saute, on ne débite pas des mois d'un coup
        s.next_run_on = _first_on_or_after(s, stale)
        if s.next_run_on is None or s.next_run_on > today:
            s.status = "completed" if s.next_run_on is None else s.status
            session.commit()
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
                try:
                    claimed = _claim(session, schedule_id, today)
                    if claimed is None:
                        break
                    run, owner_id = claimed
                    _execute(session, run, owner_id, log, now)
                except Exception:  # isolée : les autres programmations de la passe continuent
                    log.warning("Scheduled transfer %s pass failed", schedule_id, exc_info=True)
                    break
                done += 1
    return done


def _fail(session: Session, run_id: int, code: str, s, username: str | None, log) -> None:
    session.rollback()
    run = session.get(ScheduledRun, run_id)
    run.status, run.error_code = "failed", code
    notify(
        session,
        s.owner_user_id,
        "scheduled_failed",
        "Virement programmé non exécuté",
        f"{euros(s.amount_cents)} vers le compte n°{s.dst_account} le {run.run_on:%d/%m/%Y}"
        f" ({code.replace('_', ' ')}).",
    )
    session.commit()
    transactions_total.labels(result="rejected").inc()
    log_event(
        log,
        logging.WARNING,
        "scheduled_transfer_failed",
        f"Scheduled transfer {s.id} run {run.run_on} failed ({code})",
        user=username,
    )


def _execute(session: Session, run: ScheduledRun, owner_id: int, log, now) -> None:
    s = session.get(ScheduledTransfer, run.scheduled_id)
    owner = session.get(User, owner_id)
    if owner is None:
        _fail(session, run.id, "account_not_found", s, None, log)
        return
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
            notify_sender=False,  # l'émetteur reçoit « programmé exécuté » ci-dessous
        )
    except Rejection as rej:
        _fail(session, run.id, rej.code, s, owner.username, log)
        return
    except SQLAlchemyError:
        # BDD en incident après la réservation : échec enregistré si elle répond encore,
        # puis l'erreur remonte (journalisée par run_due) — jamais silencieux.
        with contextlib.suppress(SQLAlchemyError):
            _fail(session, run.id, "internal_error", s, owner.username, log)
        raise
    run = session.get(ScheduledRun, run.id)
    run.status, run.transaction_id = "executed", tx.id
    notify(
        session,
        s.owner_user_id,
        "scheduled_executed",
        "Virement programmé exécuté",
        f"{euros(s.amount_cents)} vers le compte n°{s.dst_account}.",
    )
    session.commit()
    transactions_total.labels(result="created").inc()
    log_event(
        log,
        logging.INFO,
        "scheduled_transfer_executed",
        f"Scheduled transfer {s.id} run {run.run_on} executed (transaction {tx.id})",
        user=owner.username,
    )
