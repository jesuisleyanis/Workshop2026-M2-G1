"""Cartes (#47) : liste sans PAN/CVV, gel/dégel idempotents, réglages bornés, IDOR -> 404."""

import pytest
from paykit import bearer, make_token
from resilience_db.models import Card

C = "/api/v1/cards"


@pytest.fixture
def cards(db, world):
    """alice : carte 1 (compte 1) ; bob : carte 2 (compte 3)."""
    db.add_all(
        [
            Card(
                account_id=1,
                last4="4001",
                holder="ALICE",
                expiry_month=1,
                expiry_year=2029,
                payment_limit_cents=150_000,
            ),
            Card(
                account_id=3,
                last4="4003",
                holder="BOB",
                expiry_month=3,
                expiry_year=2029,
                payment_limit_cents=150_000,
            ),
        ]
    )
    db.commit()


@pytest.fixture
def bob():
    return bearer(make_token("bob"))


def test_list_only_my_cards_without_pan_or_cvv(client, alice, cards):
    (card,) = client.get(C, headers=alice).json()
    assert card["last4"] == "4001" and card["status"] == "active"
    assert set(card) == {
        "id",
        "account_id",
        "last4",
        "holder",
        "expiry_month",
        "expiry_year",
        "status",
        "payment_limit_cents",
        "contactless",
        "online_payments",
    }, "aucun numéro complet ni CVV"


def test_freeze_and_unfreeze_are_idempotent_with_one_event_per_change(
    client, alice, cards, log_lines
):
    for _ in range(2):
        r = client.post(f"{C}/1/freeze", headers=alice)
        assert r.status_code == 200 and r.json()["status"] == "frozen"
    assert len(log_lines("card_frozen")) == 1, "pas de second événement si l'état ne change pas"
    for _ in range(2):
        assert client.post(f"{C}/1/unfreeze", headers=alice).json()["status"] == "active"
    assert len(log_lines("card_unfrozen")) == 1


def test_patch_settings_within_bounds(client, alice, cards, log_lines):
    r = client.patch(
        f"{C}/1", headers=alice, json={"payment_limit_cents": 50_000, "contactless": False}
    )
    assert r.status_code == 200
    body = r.json()
    assert (body["payment_limit_cents"], body["contactless"], body["online_payments"]) == (
        50_000,
        False,
        True,
    ), "seuls les champs envoyés changent"
    (e,) = log_lines("card_settings_changed")
    assert "contactless" in e["message"] and "payment_limit_cents" in e["message"]


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"payment_limit_cents": -1},
        {"payment_limit_cents": 1_000_001},
        {"payment_limit_cents": 10.5},
        {"payment_limit_cents": True},
        {"contactless": "yes"},
        {"contactless": None},
        {"status": "active"},
        {"last4": "9999"},
    ],
)
def test_patch_rejects_out_of_bounds_or_unknown_fields(client, alice, cards, body):
    r = client.patch(f"{C}/1", headers=alice, json=body)
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error"


def test_frozen_card_settings_are_locked(client, alice, cards):
    client.post(f"{C}/1/freeze", headers=alice)
    r = client.patch(f"{C}/1", headers=alice, json={"online_payments": False})
    assert r.status_code == 409 and r.json()["error"]["code"] == "card_frozen"


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("post", f"{C}/2/freeze", None),
        ("post", f"{C}/2/unfreeze", None),
        ("patch", f"{C}/2", {"contactless": False}),
        ("post", f"{C}/999/freeze", None),
    ],
)
def test_idor_other_users_card_is_404_like_unknown(client, alice, bob, cards, method, path, body):
    kwargs = {"headers": alice} | ({"json": body} if body else {})
    r = getattr(client, method)(path, **kwargs)
    assert r.status_code == 404 and r.json()["error"]["code"] == "card_not_found"
    assert client.get(C, headers=bob).json()[0]["status"] == "active", "carte de bob intacte"


def test_bearer_required_and_ids_bounded(client, alice, cards):
    assert client.get(C).status_code == 401
    assert client.post(f"{C}/1/freeze").status_code == 401
    assert client.post(f"{C}/{2**31}/freeze", headers=alice).status_code == 422
