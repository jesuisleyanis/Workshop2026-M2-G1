"""Virements programmés (#48) : règles d'échéance, API, exécuteur idempotent (horloge injectée)."""

import logging
from datetime import UTC, date, datetime

import pytest
from fastapi.testclient import TestClient
from paykit import JWT_SECRET, bearer, make_token
from resilience_db import make_session_factory
from resilience_db.models import Account, ScheduledRun, ScheduledTransfer, Transaction
from sqlalchemy.exc import IntegrityError

from payment_api import schedules
from payment_api.config import Settings
from payment_api.main import create_app

S = "/api/v1/scheduled-transfers"
LOG = logging.getLogger("payment-api")


class Clock:
    def __init__(self, at):
        self.at = at

    def __call__(self):
        return self.at


@pytest.fixture
def clock():
    return Clock(datetime(2026, 10, 21, 9, 0, tzinfo=UTC))


@pytest.fixture
def alice(world, clock):
    """Jeton dont `auth_time` suit l'horloge injectée (step-up #51 évalué à cette heure-là)."""
    from paykit import bearer, make_token

    return bearer(make_token("alice", auth_time=int(clock().timestamp())))


@pytest.fixture
def api(engine, world, clock):
    settings = Settings(jwt_secret=JWT_SECRET, run_migrations=False, scheduler_enabled=False)
    return TestClient(create_app(settings, engine, now=clock))


def _body(**over):
    return {
        "src_account": 1,
        "dst_account": 3,
        "amount_cents": 1_000,
        "frequency": "monthly",
        "start_on": "2026-10-21",
        **over,
    }


def _run(engine, clock):
    return schedules.run_due(make_session_factory(engine), LOG, clock)


# ------------------------------------------------------------------ règles d'échéance
@pytest.mark.parametrize(
    ("start", "current", "expected"),
    [
        (date(2026, 1, 31), date(2026, 1, 31), date(2026, 2, 28)),  # fin de mois
        (date(2026, 1, 31), date(2026, 2, 28), date(2026, 3, 31)),  # revient au 31
        (date(2028, 1, 31), date(2028, 1, 31), date(2028, 2, 29)),  # bissextile
        (date(2026, 12, 15), date(2026, 12, 15), date(2027, 1, 15)),  # changement d'année
    ],
)
def test_monthly_is_anchored_on_the_start_day(start, current, expected):
    s = ScheduledTransfer(frequency="monthly", start_on=start, end_on=None)
    assert schedules.following(s, current) == expected


def test_weekly_once_and_end_date():
    weekly = ScheduledTransfer(frequency="weekly", start_on=date(2026, 10, 21), end_on=None)
    assert schedules.following(weekly, date(2026, 10, 21)) == date(2026, 10, 28)
    weekly.end_on = date(2026, 10, 27)
    assert schedules.following(weekly, date(2026, 10, 21)) is None
    once = ScheduledTransfer(frequency="once", start_on=date(2026, 10, 21), end_on=None)
    assert schedules.following(once, date(2026, 10, 21)) is None


# ------------------------------------------------------------------ API
def test_create_list_pause_resume_cancel(api, alice):
    r = api.post(S, headers=alice, json=_body(category="housing", end_on="2027-03-21"))
    assert r.status_code == 201
    created = r.json()
    assert (created["status"], created["next_run_on"], created["last_run"]) == (
        "active",
        "2026-10-21",
        None,
    )
    sid = created["id"]
    assert api.patch(f"{S}/{sid}", headers=alice, json={"status": "paused"}).json()["status"] == (
        "paused"
    )
    assert api.patch(f"{S}/{sid}", headers=alice, json={"status": "active"}).json()["status"] == (
        "active"
    )
    assert api.delete(f"{S}/{sid}", headers=alice).status_code == 204
    (row,) = api.get(S, headers=alice).json()
    assert (row["status"], row["next_run_on"]) == ("cancelled", None), "reste listée"
    r = api.patch(f"{S}/{sid}", headers=alice, json={"status": "active"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "schedule_closed"


@pytest.mark.parametrize(
    ("over", "status", "code"),
    [
        ({"src_account": 3, "dst_account": 1}, 404, "account_not_found"),
        ({"dst_account": 999}, 404, "destination_not_found"),
        ({"dst_account": 1}, 422, "same_account"),
        ({"amount_cents": 0}, 422, "invalid_amount"),
        ({"amount_cents": 100_000_001}, 422, "amount_too_large"),
        ({"start_on": "2026-10-20"}, 422, "invalid_dates"),
        ({"start_on": "2027-10-23"}, 422, "invalid_dates"),
        ({"end_on": "2026-10-20"}, 422, "invalid_dates"),
        ({"frequency": "daily"}, 422, "validation_error"),
        ({"category": "crypto"}, 422, "validation_error"),
    ],
)
def test_create_is_validated(api, alice, over, status, code):
    r = api.post(S, headers=alice, json=_body(**over))
    assert r.status_code == status and r.json()["error"]["code"] == code


def test_limit_of_active_schedules(api, alice, monkeypatch):
    monkeypatch.setattr(schedules, "MAX_ACTIVE_PER_USER", 1)
    assert api.post(S, headers=alice, json=_body()).status_code == 201
    r = api.post(S, headers=alice, json=_body())
    assert r.status_code == 409 and r.json()["error"]["code"] == "schedule_limit"


def test_idor_other_users_schedule_is_404(api, alice):
    sid = api.post(S, headers=alice, json=_body()).json()["id"]
    bob = bearer(make_token("bob"))
    assert api.get(S, headers=bob).json() == []
    for call in (
        lambda: api.patch(f"{S}/{sid}", headers=bob, json={"status": "paused"}),
        lambda: api.delete(f"{S}/{sid}", headers=bob),
    ):
        r = call()
        assert r.status_code == 404 and r.json()["error"]["code"] == "schedule_not_found"
    assert api.get(S, headers=alice).json()[0]["status"] == "active"


def test_pause_body_is_strict(api, alice):
    sid = api.post(S, headers=alice, json=_body()).json()["id"]
    for body in ({"status": "cancelled"}, {"status": "active", "amount_cents": 1}, {}):
        assert api.patch(f"{S}/{sid}", headers=alice, json=body).status_code == 422


# ------------------------------------------------------------------ exécuteur
def test_once_runs_exactly_once_then_completes(api, alice, engine, clock, db, log_lines):
    api.post(S, headers=alice, json=_body(frequency="once"))
    assert _run(engine, clock) == 1
    assert _run(engine, clock) == 0, "même jour : rien de plus"
    clock.at = datetime(2026, 12, 1, tzinfo=UTC)
    assert _run(engine, clock) == 0
    (row,) = api.get(S, headers=alice).json()
    assert row["status"] == "completed" and row["last_run"]["status"] == "executed"
    assert db.query(Transaction).filter_by(request_id="sched-1-2026-10-21").count() == 1
    (e,) = log_lines("scheduled_transfer_executed")
    assert e["user"] == "alice"


def test_weekly_runs_each_week_and_catches_up_after_downtime(api, alice, engine, clock, db):
    api.post(S, headers=alice, json=_body(frequency="weekly", amount_cents=100))
    _run(engine, clock)  # 21/10
    clock.at = datetime(2026, 11, 11, 8, 0, tzinfo=UTC)  # 3 semaines d'arrêt
    assert _run(engine, clock) == 3, "28/10, 04/11, 11/11 rattrapés, une fois chacun"
    runs = [r.run_on for r in db.query(ScheduledRun).order_by(ScheduledRun.run_on)]
    assert runs == [date(2026, 10, 21), date(2026, 10, 28), date(2026, 11, 4), date(2026, 11, 11)]
    assert api.get(S, headers=alice).json()[0]["next_run_on"] == "2026-11-18"


def test_monthly_end_of_month_with_injected_clock(api, alice, engine, clock, db):
    clock.at = datetime(2026, 1, 31, 6, 0, tzinfo=UTC)
    api.post(S, headers=alice, json=_body(start_on="2026-01-31", amount_cents=100))
    _run(engine, clock)
    clock.at = datetime(2026, 2, 28, 6, 0, tzinfo=UTC)
    assert _run(engine, clock) == 1
    assert api.get(S, headers=alice).json()[0]["next_run_on"] == "2026-03-31"


def test_double_execution_is_impossible_after_restart_or_with_two_replicas(
    api, alice, engine, clock, db
):
    api.post(S, headers=alice, json=_body(frequency="once", amount_cents=100))
    # Réplique A réserve l'échéance (« redémarrée » juste après) ; réplique B repasse.
    with make_session_factory(engine)() as session:
        claimed = schedules._claim(session, 1, clock().date())
    assert claimed is not None
    # La réservation est faite : aucune autre passe (B, ou A après redémarrage) ne réexécute.
    assert _run(engine, clock) == 0
    assert db.query(Transaction).count() == 0, "au plus une fois : jamais deux"
    # La contrainte UNIQUE tranche même si deux passes lisent l'échéance en même temps.
    with make_session_factory(engine)() as session:
        session.add(ScheduledRun(scheduled_id=1, run_on=date(2026, 10, 21), status="pending"))
        with pytest.raises(IntegrityError):
            session.commit()


def test_failure_is_recorded_and_traced(api, alice, engine, clock, db, log_lines):
    api.post(S, headers=alice, json=_body(src_account=2, amount_cents=99_999))  # solde 5 €
    assert _run(engine, clock) == 1
    (row,) = api.get(S, headers=alice).json()
    assert row["last_run"] == {
        "run_on": "2026-10-21",
        "status": "failed",
        "error_code": "insufficient_funds",
    }
    assert row["status"] == "active" and row["next_run_on"] == "2026-11-21", (
        "réessayée le mois suivant"
    )
    (e,) = log_lines("scheduled_transfer_failed")
    assert "insufficient_funds" in e["message"]
    db.expire_all()
    assert db.get(Account, 2).balance_cents == 500


def test_paused_schedule_is_not_executed(api, alice, engine, clock):
    sid = api.post(S, headers=alice, json=_body()).json()["id"]
    api.patch(f"{S}/{sid}", headers=alice, json={"status": "paused"})
    assert _run(engine, clock) == 0


def test_executor_goes_through_the_monthly_limit(api, alice, engine, clock, db):
    db.get(Account, 1).monthly_limit_cents = 500
    db.commit()
    api.post(S, headers=alice, json=_body(amount_cents=1_000))
    _run(engine, clock)
    assert api.get(S, headers=alice).json()[0]["last_run"]["error_code"] == "limit_exceeded"


def test_background_executor_runs_in_the_app_lifespan(engine, world, db, clock):
    import time

    settings = Settings(jwt_secret=JWT_SECRET, run_migrations=False, scheduler_interval_s=0.05)
    alice = bearer(make_token("alice"))
    with TestClient(create_app(settings, engine, now=clock)) as c:
        assert (
            c.post(S, headers=alice, json=_body(frequency="once", amount_cents=100)).status_code
            == 201
        )
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            row = c.get(S, headers=alice).json()[0]
            if row["status"] == "completed":
                break
            time.sleep(0.05)
    assert row["status"] == "completed" and row["last_run"]["status"] == "executed"


def test_resume_skips_occurrences_missed_during_the_pause(api, alice, engine, clock, db):
    sid = api.post(S, headers=alice, json=_body(frequency="weekly", amount_cents=100)).json()["id"]
    api.patch(f"{S}/{sid}", headers=alice, json={"status": "paused"})
    clock.at = datetime(2026, 12, 2, 9, 0, tzinfo=UTC)  # 6 semaines plus tard
    row = api.patch(f"{S}/{sid}", headers=alice, json={"status": "active"}).json()
    assert row["next_run_on"] == "2026-12-02", "première échéance à venir, pas celles manquées"
    assert _run(engine, clock) == 1


def test_very_old_occurrences_are_skipped_not_debited(api, alice, engine, clock, db):
    api.post(S, headers=alice, json=_body(frequency="weekly", amount_cents=100))
    clock.at = datetime(2027, 6, 1, 9, 0, tzinfo=UTC)  # ~32 semaines d'arrêt
    executed = _run(engine, clock)
    assert executed <= 5, "rattrapage borné à 31 jours"
    assert db.query(Transaction).count() == executed


def test_db_failure_after_claim_is_recorded_and_other_schedules_continue(
    api, alice, engine, clock, db, monkeypatch, log_lines
):
    from sqlalchemy.exc import OperationalError

    api.post(S, headers=alice, json=_body(frequency="once", amount_cents=100))
    api.post(S, headers=alice, json=_body(frequency="once", amount_cents=200, dst_account=2))
    real = schedules.transfer
    calls = []

    def flaky(session, user, src, dst, *a, **kw):
        calls.append(dst)
        if len(calls) == 1:
            raise OperationalError("UPDATE", {}, Exception("db down"))
        return real(session, user, src, dst, *a, **kw)

    monkeypatch.setattr(schedules, "transfer", flaky)
    assert _run(engine, clock) == 1, "l'échec isolé n'arrête pas la passe"
    runs = {r["id"]: r["last_run"] for r in api.get(S, headers=alice).json()}
    assert sorted((r["status"], r["error_code"]) for r in runs.values()) == [
        ("executed", None),
        ("failed", "internal_error"),
    ]
    assert any("internal_error" in e["message"] for e in log_lines("scheduled_transfer_failed"))


def test_out_of_range_account_ids_are_422_not_db_errors(api, alice):
    r = api.post(S, headers=alice, json=_body(src_account=2**31))
    assert r.status_code == 422


def test_schedule_audit_trail(api, alice, log_lines):
    sid = api.post(S, headers=alice, json=_body()).json()["id"]
    api.post(S, headers=alice, json=_body(dst_account=999))
    api.patch(f"{S}/{sid}", headers=alice, json={"status": "paused"})
    api.delete(f"{S}/{sid}", headers=alice)
    assert len(log_lines("scheduled_transfer_created")) == 1
    (rej,) = log_lines("scheduled_transfer_rejected")
    assert "destination_not_found" in rej["message"]
    assert len(log_lines("scheduled_transfer_changed")) == 2


def test_claim_locks_the_schedule_row():
    from sqlalchemy.orm import Session

    stmt = {}

    class Spy(Session):
        def get(self, entity, ident, **kw):
            stmt["for_update"] = kw.get("with_for_update")

    with Spy() as s:
        assert schedules._claim(s, 1, date(2026, 10, 21)) is None
    assert stmt["for_update"] is True, "SELECT ... FOR UPDATE"
