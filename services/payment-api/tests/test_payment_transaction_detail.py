"""GET /api/v1/transactions/{id} (#45) : propriétaire (émetteur ou destinataire) sinon 404."""

import pytest
from paykit import bearer, make_token
from resilience_db.models import Account, User

TX = "/api/v1/transactions"


@pytest.fixture
def bob():
    return bearer(make_token("bob"))


@pytest.fixture
def sent(client, alice):
    r = client.post(
        TX,
        headers=alice,
        json={"src_account": 1, "dst_account": 3, "amount_cents": 250, "category": "food"},
    )
    return r.json()


def test_sender_sees_full_detail_with_request_id(client, alice, sent):
    r = client.get(f"{TX}/{sent['id']}", headers=alice)
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == sent["id"] and body["amount_cents"] == 250
    assert body["category"] == "food" and body["request_id"] == sent["request_id"]


def test_recipient_sees_it_without_the_sender_category(client, bob, sent):
    body = client.get(f"{TX}/{sent['id']}", headers=bob).json()
    assert body["dst_account"] == 3 and body["category"] is None


def test_third_party_gets_404_like_an_unknown_id(client, db, sent):
    carol = User(username="carol", password_hash="x")
    carol.accounts.append(Account(iban_fake="FR76 C1", balance_cents=0, currency="EUR"))
    db.add(carol)
    db.commit()
    stranger = client.get(f"{TX}/{sent['id']}", headers=bearer(make_token("carol")))
    unknown = client.get(f"{TX}/999999", headers=bearer(make_token("carol")))
    assert stranger.status_code == unknown.status_code == 404
    assert (
        stranger.json()["error"]["code"]
        == unknown.json()["error"]["code"]
        == ("transaction_not_found")
    )


@pytest.mark.parametrize("bad", ["0", "-1", str(2**31), "abc"])
def test_invalid_ids_are_422_never_a_db_error(client, alice, bad):
    assert client.get(f"{TX}/{bad}", headers=alice).status_code == 422


def test_bearer_required(client, sent):
    assert client.get(f"{TX}/{sent['id']}").status_code == 401
