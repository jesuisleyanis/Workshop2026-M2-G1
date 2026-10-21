"""Bénéficiaires (#43) : CRUD, doublon, compte inconnu, soi-même, IDOR."""

import pytest
from paykit import bearer, make_token

B = "/api/v1/beneficiaries"


def _ids(rows):
    # SQLite perd le fuseau à la relecture (PostgreSQL non) : on compare sans created_at.
    return [{k: v for k, v in r.items() if k != "created_at"} for r in rows]


@pytest.fixture
def bob():
    return bearer(make_token("bob"))


def _add(client, headers, name="Bob", iban="FR76 B1"):
    return client.post(B, headers=headers, json={"display_name": name, "iban_fake": iban})


def test_add_list_delete_roundtrip(client, alice):
    assert client.get(B, headers=alice).json() == []
    r = _add(client, alice, name="  Bob   Dupont ")
    assert r.status_code == 201
    created = r.json()
    assert created["display_name"] == "Bob Dupont", "espaces normalisés"
    assert (created["account_id"], created["iban_fake"]) == (3, "FR76 B1")
    assert _ids(client.get(B, headers=alice).json()) == _ids([created])
    assert client.delete(f"{B}/{created['id']}", headers=alice).status_code == 204
    assert client.get(B, headers=alice).json() == []


def test_iban_is_matched_ignoring_spaces_and_case(client, alice):
    r = _add(client, alice, iban="fr76b1")
    assert r.status_code == 201 and r.json()["iban_fake"] == "FR76 B1"


def test_duplicate_is_409(client, alice):
    _add(client, alice)
    r = _add(client, alice, name="Encore Bob", iban="FR76B1")
    assert r.status_code == 409 and r.json()["error"]["code"] == "beneficiary_exists"


def test_unknown_iban_is_404(client, alice):
    r = _add(client, alice, iban="FR76 0000 NOPE")
    assert r.status_code == 404 and r.json()["error"]["code"] == "account_not_found"


def test_own_account_is_refused(client, alice):
    r = _add(client, alice, iban="FR76 A2")
    assert r.status_code == 422 and r.json()["error"]["code"] == "own_account"


@pytest.mark.parametrize(
    "body",
    [
        {"display_name": "", "iban_fake": "FR76 B1"},
        {"display_name": "   ", "iban_fake": "FR76 B1"},
        {"display_name": "x" * 65, "iban_fake": "FR76 B1"},
        {"display_name": "Bob\u0000", "iban_fake": "FR76 B1"},
        {"display_name": "Bob"},
    ],
)
def test_invalid_body_is_422_validation_error(client, alice, body):
    r = client.post(B, headers=alice, json=body)
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error"


def test_idor_other_users_beneficiary_is_invisible_and_404_on_delete(client, alice, bob):
    mine = _add(client, alice).json()
    assert client.get(B, headers=bob).json() == []
    r = client.delete(f"{B}/{mine['id']}", headers=bob)
    assert r.status_code == 404 and r.json()["error"]["code"] == "beneficiary_not_found"
    assert _ids(client.get(B, headers=alice).json()) == _ids([mine]), "intact"


def test_unknown_id_404_and_out_of_range_id_422_not_db_error(client, alice):
    assert client.delete(f"{B}/999", headers=alice).status_code == 404
    r = client.delete(f"{B}/{2**31}", headers=alice)
    assert r.status_code == 422, "jamais un 503 db_error (faux signal ML)"


@pytest.mark.parametrize(("method", "path"), [("get", B), ("post", B), ("delete", f"{B}/1")])
def test_bearer_is_required(client, method, path):
    assert getattr(client, method)(path).status_code == 401


def test_limit_per_user(client, alice, monkeypatch):
    from payment_api import beneficiaries

    monkeypatch.setattr(beneficiaries, "MAX_BENEFICIARIES", 1)
    assert _add(client, alice).status_code == 201
    r = _add(client, alice, iban="FR76 A1")  # propre compte : la borne passe après
    assert r.json()["error"]["code"] == "own_account"
    monkeypatch.setattr(beneficiaries, "MAX_BENEFICIARIES", 0)
    r = _add(client, alice, iban="FR76 B1")
    assert r.status_code == 409 and r.json()["error"]["code"] == "beneficiary_limit"


def test_audit_trail_events_without_the_typed_iban(client, alice, log_lines):
    created = _add(client, alice).json()
    _add(client, alice, iban="FR76 SECRET-PROBE")
    client.delete(f"{B}/{created['id']}", headers=alice)
    (added,) = log_lines("beneficiary_added")
    (rejected,) = log_lines("beneficiary_rejected")
    (removed,) = log_lines("beneficiary_removed")
    assert added["user"] == rejected["user"] == removed["user"] == "alice"
    assert rejected["level"] == "WARNING" and "account_not_found" in rejected["message"]
    assert "SECRET-PROBE" not in str(log_lines()), "l'IBAN sondé n'est jamais journalisé"
    from resilience_common.logging import NORMALIZED_EVENTS

    assert {"beneficiary_added", "beneficiary_rejected", "beneficiary_removed"} <= NORMALIZED_EVENTS


def test_non_duplicate_integrity_error_is_a_db_error_not_beneficiary_exists(
    client, alice, monkeypatch
):
    from sqlalchemy.exc import IntegrityError
    from sqlalchemy.orm import Session

    def broken_commit(self):
        raise IntegrityError("INSERT", {}, Exception("FOREIGN KEY constraint failed"))

    monkeypatch.setattr(Session, "commit", broken_commit)
    r = _add(client, alice)
    assert r.status_code == 503 and r.json()["error"]["code"] == "db_unavailable"
