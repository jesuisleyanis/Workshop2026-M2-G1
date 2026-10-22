"""Notifications (#49) : génération sur chaque événement, lecture, rétention, IDOR."""

from datetime import UTC, datetime

import pytest
from paykit import bearer, make_token
from resilience_db import make_session_factory
from resilience_db.models import Account, Card, Notification

from payment_api import notifications

N = "/api/v1/notifications"
TX = "/api/v1/transactions"


@pytest.fixture
def bob():
    return bearer(make_token("bob"))


def _send(client, h, amount, src=1, dst=3):
    return client.post(
        TX, headers=h, json={"src_account": src, "dst_account": dst, "amount_cents": amount}
    )


def _types(client, h, unread=False):
    return [n["type"] for n in client.get(N, headers=h, params={"unread": unread}).json()]


def test_transfer_notifies_sender_and_recipient_in_french(client, alice, bob):
    _send(client, alice, 1_250)
    (sent,) = client.get(N, headers=alice).json()
    assert (sent["type"], sent["title"], sent["read_at"]) == (
        "transfer_sent",
        "Virement émis",
        None,
    )
    assert sent["body"] == "12,50 € vers le compte n°3."
    assert _types(client, bob) == ["transfer_received"]


def test_internal_transfer_does_not_notify(client, alice):
    _send(client, alice, 100, src=1, dst=2)
    assert _types(client, alice) == []


@pytest.mark.parametrize(
    ("limit", "amount", "reason"),
    [(None, 99_999, "solde insuffisant"), (50, 100, "plafond mensuel atteint")],
)
def test_rejected_transfer_notifies_the_sender(client, alice, db, limit, amount, reason):
    db.get(Account, 1).monthly_limit_cents = limit
    db.commit()
    src = 2 if limit is None else 1
    _send(client, alice, amount, src=src)
    (n,) = client.get(N, headers=alice).json()
    assert n["type"] == "transfer_rejected" and reason in n["body"]


def test_limit_80_alert_fires_once_when_crossing(client, alice, db):
    db.get(Account, 1).monthly_limit_cents = 1_000
    db.commit()
    _send(client, alice, 700)  # 70 %
    _send(client, alice, 150)  # 85 % : franchit le seuil
    _send(client, alice, 50)  # 90 % : déjà franchi
    assert _types(client, alice).count("limit_80") == 1


def test_card_freeze_and_unfreeze_notify(client, alice, db):
    db.add(
        Card(
            account_id=1,
            last4="4001",
            holder="A",
            expiry_month=1,
            expiry_year=2029,
            payment_limit_cents=1,
        )
    )
    db.commit()
    client.post("/api/v1/cards/1/freeze", headers=alice)
    client.post("/api/v1/cards/1/freeze", headers=alice)  # idempotent : pas de doublon
    client.post("/api/v1/cards/1/unfreeze", headers=alice)
    assert _types(client, alice) == ["card_unfrozen", "card_frozen"]


def test_scheduled_executed_and_failed_notify_owner_once(client, alice, bob, engine):
    import logging

    from payment_api import schedules

    body = {
        "src_account": 1,
        "dst_account": 3,
        "amount_cents": 100,
        "frequency": "once",
        "start_on": datetime.now(UTC).date().isoformat(),
    }
    client.post("/api/v1/scheduled-transfers", headers=alice, json=body)
    client.post(
        "/api/v1/scheduled-transfers",
        headers=alice,
        json={**body, "src_account": 2, "amount_cents": 99_999},
    )
    schedules.run_due(make_session_factory(engine), logging.getLogger("payment-api"))
    mine = _types(client, alice)
    assert sorted(mine) == ["scheduled_executed", "scheduled_failed"], "pas de « émis » en double"
    assert _types(client, bob) == ["transfer_received"]


def test_mark_one_read_and_read_all_with_unread_filter(client, alice):
    for _ in range(3):
        _send(client, alice, 1)
    first = client.get(N, headers=alice).json()[0]
    r = client.post(f"{N}/{first['id']}/read", headers=alice)
    assert r.status_code == 200 and r.json()["read_at"] is not None
    again = client.post(f"{N}/{first['id']}/read", headers=alice).json()
    # SQLite perd le fuseau à la relecture : même instant, sans le « Z ».
    assert again["read_at"].rstrip("Z") == r.json()["read_at"].rstrip("Z"), "idempotent"
    assert len(client.get(N, headers=alice, params={"unread": True}).json()) == 2
    assert client.post(f"{N}/read-all", headers=alice).json() == {"updated": 2}
    assert client.get(N, headers=alice, params={"unread": True}).json() == []


def test_idor_other_users_notification_is_404(client, alice, bob):
    _send(client, alice, 1)
    nid = client.get(N, headers=alice).json()[0]["id"]
    r = client.post(f"{N}/{nid}/read", headers=bob)
    assert r.status_code == 404 and r.json()["error"]["code"] == "notification_not_found"
    assert client.get(N, headers=alice).json()[0]["read_at"] is None
    assert client.post(f"{N}/read-all", headers=bob).json() == {"updated": 1}, "le reçu de bob"
    assert client.get(N, headers=alice).json()[0]["read_at"] is None, "read-all cloisonné"


def test_retention_is_applied_off_the_hot_path(db, world, client, alice):
    alice_id = world["alice"].id
    for i in range(notifications.RETENTION + 30):
        notifications.notify(db, alice_id, "transfer_sent", "t", f"b{i}")
    db.commit()
    assert (
        db.query(Notification).filter_by(user_id=alice_id).count() == notifications.RETENTION + 30
    )
    notifications.prune_all(db)  # tâche de fond
    kept = db.query(Notification).filter_by(user_id=alice_id).order_by(Notification.id).all()
    assert len(kept) == notifications.RETENTION
    assert kept[-1].body == f"b{notifications.RETENTION + 29}", "les plus récentes gardées"
    for i in range(5):
        notifications.notify(db, alice_id, "transfer_sent", "t", f"x{i}")
    db.commit()
    assert len(client.get(N, headers=alice).json()) == notifications.RETENTION, "et à la lecture"


def test_notify_rejects_unknown_types_before_reaching_the_database(db, world):
    with pytest.raises(ValueError):
        notifications.notify(db, world["alice"].id, "trasfer_sent", "t", "b")


def test_unread_count_for_the_bell(client, alice):
    for _ in range(3):
        _send(client, alice, 1)
    assert client.get(f"{N}/unread-count", headers=alice).json() == {"count": 3}
    client.post(f"{N}/read-all", headers=alice)
    assert client.get(f"{N}/unread-count", headers=alice).json() == {"count": 0}


def test_rejected_internal_transfer_does_not_notify(client, alice):
    _send(client, alice, 99_999, src=2, dst=1)
    assert _types(client, alice) == []


def test_bearer_required(client):
    assert client.get(N).status_code == 401
    assert client.post(f"{N}/read-all").status_code == 401
