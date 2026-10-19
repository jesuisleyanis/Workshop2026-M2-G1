"""Règles métier : comptes, virements, solde insuffisant, isolation entre utilisateurs."""

import pytest
from paykit import bearer, make_token, sample
from resilience_db.models import Account, Transaction
from sqlalchemy import select

TX = "/api/v1/transactions"


def _balance(db, account_id):
    db.expire_all()
    return db.get(Account, account_id).balance_cents


def test_accounts_returns_only_own_accounts(client, alice):
    r = client.get("/api/v1/accounts", headers=alice)
    assert r.status_code == 200
    assert [a["id"] for a in r.json()] == [1, 2]
    assert set(r.json()[0]) == {"id", "iban_fake", "balance_cents", "currency"}
    bob = client.get("/api/v1/accounts", headers=bearer(make_token("bob"))).json()
    assert [a["id"] for a in bob] == [3]


def test_transfer_debits_source_and_credits_destination_atomically(client, alice, db):
    r = client.post(
        TX, headers=alice, json={"src_account": 1, "dst_account": 3, "amount_cents": 2_500}
    )
    assert r.status_code == 201
    body = r.json()
    assert (body["status"], body["amount_cents"], body["src_account"], body["dst_account"]) == (
        "created",
        2_500,
        1,
        3,
    )
    assert body["request_id"] == r.headers["X-Request-ID"]  # traçabilité de bout en bout
    assert _balance(db, 1) == 7_500 and _balance(db, 3) == 7_500


def test_insufficient_funds_is_rejected_and_balances_untouched(client, alice, db):
    r = client.post(
        TX, headers=alice, json={"src_account": 2, "dst_account": 3, "amount_cents": 501}
    )
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "insufficient_funds"
    assert _balance(db, 2) == 500 and _balance(db, 3) == 5_000
    # la tentative est tracée (R2) avec le statut rejected
    (tx,) = db.scalars(select(Transaction)).all()
    assert tx.status == "rejected" and tx.amount_cents == 501


def test_exact_balance_can_be_spent(client, alice, db):
    r = client.post(
        TX, headers=alice, json={"src_account": 2, "dst_account": 3, "amount_cents": 500}
    )
    assert r.status_code == 201 and _balance(db, 2) == 0


@pytest.mark.parametrize("amount", [0, -100])
def test_non_positive_amount_is_rejected(client, alice, amount, db):
    r = client.post(
        TX, headers=alice, json={"src_account": 1, "dst_account": 3, "amount_cents": amount}
    )
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_amount"
    assert _balance(db, 1) == 10_000 and _balance(db, 3) == 5_000  # pas de virement inversé


def test_amount_above_maximum_is_rejected(client, alice):
    r = client.post(
        TX, headers=alice, json={"src_account": 1, "dst_account": 3, "amount_cents": 10**12}
    )
    assert r.json()["error"]["code"] == "amount_too_large"


def test_same_account_is_rejected(client, alice):
    r = client.post(
        TX, headers=alice, json={"src_account": 1, "dst_account": 1, "amount_cents": 10}
    )
    assert r.json()["error"]["code"] == "same_account"


def test_cannot_spend_from_someone_elses_account(client, alice, db):
    r = client.post(
        TX, headers=alice, json={"src_account": 3, "dst_account": 1, "amount_cents": 100}
    )
    assert r.status_code == 404 and r.json()["error"]["code"] == "account_not_found"
    assert _balance(db, 3) == 5_000


def test_unknown_destination_is_rejected(client, alice, db):
    r = client.post(
        TX, headers=alice, json={"src_account": 1, "dst_account": 999, "amount_cents": 100}
    )
    assert r.status_code == 404 and r.json()["error"]["code"] == "destination_not_found"
    assert _balance(db, 1) == 10_000


def test_currency_mismatch_is_rejected(client, alice, db):
    db.get(Account, 3).currency = "USD"
    db.commit()
    r = client.post(
        TX, headers=alice, json={"src_account": 1, "dst_account": 3, "amount_cents": 100}
    )
    assert r.json()["error"]["code"] == "currency_mismatch"


@pytest.mark.parametrize("amount", [10.5, "100", True, None])
def test_non_integer_amounts_are_422_validation_errors(client, alice, amount):
    r = client.post(
        TX, headers=alice, json={"src_account": 1, "dst_account": 3, "amount_cents": amount}
    )
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error"


def test_history_lists_own_transactions_newest_first_and_hides_others(client, alice):
    bob = bearer(make_token("bob"))
    client.post(TX, headers=alice, json={"src_account": 1, "dst_account": 3, "amount_cents": 100})
    client.post(TX, headers=alice, json={"src_account": 1, "dst_account": 3, "amount_cents": 200})
    client.post(TX, headers=bob, json={"src_account": 3, "dst_account": 2, "amount_cents": 50})
    amounts = [t["amount_cents"] for t in client.get(TX, headers=alice).json()]
    assert amounts == [50, 200, 100]  # alice voit aussi le crédit reçu de bob
    # bob est partie à ses propres virements et aux deux crédits reçus d'alice
    assert [t["amount_cents"] for t in client.get(TX, headers=bob).json()] == [50, 200, 100]
    assert len(client.get(f"{TX}?limit=1", headers=alice).json()) == 1
    assert client.get(f"{TX}?limit=0", headers=alice).status_code == 422


def test_history_hides_transactions_between_other_users(client, db):
    from resilience_db.models import User

    client.post(
        TX,
        headers=bearer(make_token("bob")),
        json={"src_account": 3, "dst_account": 1, "amount_cents": 5},
    )
    carol = User(username="carol", password_hash="x")
    carol.accounts.append(Account(iban_fake="FR76 C1", balance_cents=0, currency="EUR"))
    db.add(carol)
    db.commit()
    assert client.get(TX, headers=bearer(make_token("carol"))).json() == []


def test_transaction_metrics_increment_per_result(client, alice):
    created0 = sample("resilience_transactions_total", result="created")
    rejected0 = sample("resilience_transactions_total", result="rejected")
    client.post(TX, headers=alice, json={"src_account": 1, "dst_account": 3, "amount_cents": 100})
    client.post(
        TX, headers=alice, json={"src_account": 2, "dst_account": 3, "amount_cents": 99_999}
    )
    assert sample("resilience_transactions_total", result="created") == created0 + 1
    assert sample("resilience_transactions_total", result="rejected") == rejected0 + 1


def test_db_check_constraint_is_a_backstop_against_negative_balance(db, world):
    from sqlalchemy.exc import IntegrityError

    db.get(Account, 2).balance_cents = -1
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
