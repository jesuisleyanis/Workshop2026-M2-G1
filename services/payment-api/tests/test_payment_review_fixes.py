"""Revue complète front/API : régressions des correctifs (ids bornés, refus de tiers, step-up
à la reprise, échec d'épargne programmée notifié, relevé non gonflable)."""

import logging
import time
from datetime import UTC, datetime

import pytest
from paykit import bearer, make_token
from resilience_db import make_session_factory
from resilience_db.models import Account, Notification, Transaction

from payment_api import schedules, statements

TX = "/api/v1/transactions"


@pytest.fixture
def bob():
    return bearer(make_token("bob"))


@pytest.mark.parametrize("field", ["src_account", "dst_account"])
@pytest.mark.parametrize("value", [0, 2**31, 2**40])
def test_out_of_range_account_ids_are_422_never_a_fake_db_error(client, alice, field, value):
    body = {"src_account": 1, "dst_account": 3, "amount_cents": 1, field: value}
    r = client.post(TX, headers=alice, json=body)
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error"


def test_third_party_refusal_is_invisible_to_the_recipient(client, alice, bob):
    # bob (50 €) tente 100 € vers alice : refus persisté avec dst = compte d'alice.
    r = client.post(
        TX, headers=bob, json={"src_account": 3, "dst_account": 1, "amount_cents": 10_000}
    )
    assert r.status_code == 409
    assert client.get(TX, headers=alice).json() == [], "historique d'alice sans le refus de bob"
    (mine,) = client.get(TX, headers=bob).json()
    assert mine["status"] == "rejected", "l'émetteur voit son propre refus"
    detail = client.get(f"{TX}/{mine['id']}", headers=alice)
    assert detail.status_code == 404, "ni par id"
    assert client.get(f"{TX}/{mine['id']}", headers=bob).status_code == 200


def test_resuming_a_large_schedule_requires_step_up(client, db, world):
    db.get(Account, 1).balance_cents = 10_000_000
    db.commit()
    fresh = bearer(make_token("alice", auth_time=int(time.time())))
    stale = bearer(make_token("alice", auth_time=int(time.time()) - 3600))
    body = {
        "src_account": 1,
        "dst_account": 3,
        "amount_cents": 60_000,
        "frequency": "weekly",
        "start_on": datetime.now(UTC).date().isoformat(),
    }
    sid = client.post("/api/v1/scheduled-transfers", headers=fresh, json=body).json()["id"]
    path = f"/api/v1/scheduled-transfers/{sid}"
    assert client.patch(path, headers=stale, json={"status": "paused"}).status_code == 200
    r = client.patch(path, headers=stale, json={"status": "active"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "step_up_required"
    assert client.get("/api/v1/scheduled-transfers", headers=fresh).json()[0]["status"] == "paused"
    assert client.patch(path, headers=fresh, json={"status": "active"}).status_code == 200


def test_failed_internal_scheduled_transfer_notifies_the_owner(client, alice, engine, db):
    body = {
        "src_account": 2,
        "dst_account": 1,
        "amount_cents": 99_999,
        "frequency": "once",
        "start_on": datetime.now(UTC).date().isoformat(),
    }  # épargne interne, solde 5 €
    client.post("/api/v1/scheduled-transfers", headers=alice, json=body)
    schedules.run_due(make_session_factory(engine), logging.getLogger("payment-api"))
    db.expire_all()
    assert [n.type for n in db.query(Notification)] == ["scheduled_failed"]


def test_third_party_refusals_cannot_inflate_a_statement(client, alice, db, monkeypatch):
    monkeypatch.setattr(statements, "MAX_ROWS", 2)
    at = datetime(2026, 10, 10, tzinfo=UTC)
    db.add_all(
        [
            Transaction(
                src_account=3, dst_account=1, amount_cents=1, status="rejected", created_at=at
            )
            for _ in range(10)
        ]
        + [
            Transaction(
                src_account=1, dst_account=3, amount_cents=1, status="created", created_at=at
            )
        ]
    )
    db.commit()
    r = client.get(
        "/api/v1/statements",
        headers=alice,
        params={"account_id": 1, "from": "2026-10-01", "to": "2026-10-31", "format": "json"},
    )
    assert r.status_code == 200 and len(r.json()["rows"]) == 1
