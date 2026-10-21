"""Catégories (#44) : champ facultatif sur les virements + GET /api/v1/stats/spending."""

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from paykit import JWT_SECRET
from resilience_db.models import Account, Transaction, User

from payment_api.config import Settings
from payment_api.main import create_app

TX = "/api/v1/transactions"
SP = "/api/v1/stats/spending"
NOW = datetime(2026, 10, 21, 15, 0, tzinfo=UTC)  # mercredi


def _tx(src, dst, amount, category="transfer", status="created", at=NOW):
    return Transaction(
        src_account=src,
        dst_account=dst,
        amount_cents=amount,
        status=status,
        category=category,
        created_at=at,
    )


@pytest.fixture
def stats_client(engine, world, db):
    """alice : comptes 1 et 2 ; bob : compte 3. Horloge figée au mercredi 21/10/2026 15:00 UTC."""
    db.add_all(
        [
            _tx(1, 3, 3000, "food"),
            _tx(1, 3, 1000, "food", at=datetime(2026, 10, 19, 8, 0, tzinfo=UTC)),  # lundi
            _tx(2, 3, 1000, "leisure"),
            _tx(1, 3, 9999, "food", status="rejected"),  # refus : pas une dépense
            _tx(1, 2, 5000, "housing"),  # entre mes comptes : pas une dépense
            _tx(3, 1, 7000, "shopping"),  # reçu : pas une dépense
            _tx(1, 3, 800, "shopping", at=datetime(2026, 10, 2, 9, 0, tzinfo=UTC)),  # ce mois
            _tx(1, 3, 600, "shopping", at=datetime(2026, 9, 30, 23, 0, tzinfo=UTC)),  # hors mois
        ]
    )
    db.commit()
    settings = Settings(jwt_secret=JWT_SECRET, run_migrations=False)
    return TestClient(create_app(settings, engine, now=lambda: NOW))


def test_category_is_optional_and_defaults_to_transfer(client, alice):
    r = client.post(TX, headers=alice, json={"src_account": 1, "dst_account": 3, "amount_cents": 1})
    assert r.status_code == 201 and r.json()["category"] == "transfer"
    r = client.post(
        TX,
        headers=alice,
        json={"src_account": 1, "dst_account": 3, "amount_cents": 1, "category": "health"},
    )
    assert r.json()["category"] == "health"
    assert {t["category"] for t in client.get(TX, headers=alice).json()} == {"transfer", "health"}


def test_invalid_category_is_422_validation_error(client, alice):
    r = client.post(
        TX,
        headers=alice,
        json={"src_account": 1, "dst_account": 3, "amount_cents": 1, "category": "crypto"},
    )
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error"


def test_rejected_transfer_keeps_its_category(client, alice, db):
    client.post(
        TX,
        headers=alice,
        json={"src_account": 2, "dst_account": 3, "amount_cents": 99_999, "category": "food"},
    )
    assert db.query(Transaction).filter_by(status="rejected").one().category == "food"


def test_week_spending_excludes_rejected_internal_and_received(stats_client, alice):
    body = stats_client.get(SP, headers=alice, params={"period": "week"}).json()
    assert (body["period"], body["start"], body["end"]) == ("week", "2026-10-19", "2026-10-26")
    assert body["total_cents"] == 5000
    assert body["by_category"] == [
        {"category": "food", "amount_cents": 4000, "share": 0.8},
        {"category": "leisure", "amount_cents": 1000, "share": 0.2},
    ]
    days = {d["date"]: d["amount_cents"] for d in body["by_day"]}
    assert len(days) == 7 and days["2026-10-19"] == 1000 and days["2026-10-21"] == 4000
    assert sum(days.values()) == body["total_cents"]


def test_month_spending_is_the_calendar_month(stats_client, alice):
    body = stats_client.get(SP, headers=alice, params={"period": "month"}).json()
    assert (body["start"], body["end"]) == ("2026-10-01", "2026-11-01")
    assert len(body["by_day"]) == 31
    assert body["total_cents"] == 5800, "le 30/09 23:00 UTC est hors période"
    assert body["by_category"][0] == {"category": "food", "amount_cents": 4000, "share": 0.6897}


def test_spending_is_scoped_to_the_caller(stats_client):
    from paykit import bearer, make_token

    body = stats_client.get(SP, headers=bearer(make_token("bob"))).json()
    assert body["total_cents"] == 7000 and body["by_category"][0]["category"] == "shopping"


def test_empty_period_and_bad_period(stats_client, db):
    from paykit import bearer, make_token

    carol = User(username="carol", password_hash="x")
    carol.accounts.append(Account(iban_fake="FR76 C1", balance_cents=0, currency="EUR"))
    db.add(carol)
    db.commit()
    h = bearer(make_token("carol"))
    body = stats_client.get(SP, headers=h).json()
    assert body["total_cents"] == 0 and body["by_category"] == []
    assert stats_client.get(SP, headers=h, params={"period": "year"}).status_code == 422
    assert stats_client.get(SP).status_code == 401


def test_category_is_not_a_metric_label(client, alice):
    from prometheus_client import REGISTRY

    client.post(
        TX,
        headers=alice,
        json={"src_account": 1, "dst_account": 3, "amount_cents": 1, "category": "food"},
    )
    labels = {k for m in REGISTRY.collect() for s in m.samples for k in s.labels}
    assert "category" not in labels, "contrat §2 figé : pas de label category (cardinalité)"
