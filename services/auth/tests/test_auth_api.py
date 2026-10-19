"""Règles métier de l'API auth : register, login, JWT, anti-énumération."""

import jwt
from authkit import JWT_SECRET, PASSWORD, sample
from resilience_db.models import Account, User
from resilience_db.passwords import verify_password
from sqlalchemy import select


def test_register_creates_user_with_bcrypt_hash_and_account(client, db):
    r = client.post("/api/v1/register", json={"username": "bob_01", "password": PASSWORD})
    assert r.status_code == 201
    assert r.json()["username"] == "bob_01"
    assert "password" not in r.text and "hash" not in r.text
    user = db.scalar(select(User).where(User.username == "bob_01"))
    assert user.password_hash.startswith("$2")  # bcrypt
    assert PASSWORD not in user.password_hash
    assert verify_password(PASSWORD, user.password_hash)
    accounts = db.scalars(select(Account).where(Account.user_id == user.id)).all()
    assert len(accounts) == 1 and accounts[0].balance_cents == 0  # pas de création de monnaie


def test_register_duplicate_username_conflicts_with_contract_error(client, registered):
    r = client.post("/api/v1/register", json={"username": registered, "password": PASSWORD})
    assert r.status_code == 409
    err = r.json()["error"]
    assert err["code"] == "username_taken"
    assert set(err) == {"code", "message", "request_id"}


def test_register_rejects_weak_or_malformed_input_without_echoing_password(client):
    secret = "short"
    r = client.post("/api/v1/register", json={"username": "ok_user", "password": secret})
    assert r.status_code == 422
    assert secret not in r.text
    assert (
        client.post("/api/v1/register", json={"username": "a b", "password": PASSWORD}).status_code
        == 422
    )
    too_long = "x" * 73
    assert (
        client.post(
            "/api/v1/register", json={"username": "ok_user", "password": too_long}
        ).status_code
        == 422
    )


def test_login_returns_hs256_jwt_with_sub_and_15min_expiry(client, registered):
    r = client.post("/api/v1/login", json={"username": registered, "password": PASSWORD})
    assert r.status_code == 200
    body = r.json()
    assert body["token_type"] == "bearer" and body["expires_in"] == 900
    assert jwt.get_unverified_header(body["access_token"])["alg"] == "HS256"
    claims = jwt.decode(body["access_token"], JWT_SECRET, algorithms=["HS256"])
    assert claims["sub"] == registered
    assert claims["exp"] - claims["iat"] == 15 * 60


def test_login_wrong_password_and_unknown_user_are_indistinguishable(client, registered):
    wrong = client.post(
        "/api/v1/login", json={"username": registered, "password": "nope-nope-nope"}
    )
    unknown = client.post("/api/v1/login", json={"username": "ghost", "password": "nope-nope-nope"})
    assert wrong.status_code == unknown.status_code == 401
    w, u = wrong.json()["error"], unknown.json()["error"]
    assert (
        (w["code"], w["message"])
        == (u["code"], u["message"])
        == ("invalid_credentials", "Invalid credentials")
    )


def test_seeded_accounts_can_log_in(client, db):
    """Le module de seed réutilisable produit des comptes utilisables via l'API."""
    from resilience_db.seed import seed_demo_data

    seed_demo_data(db, "seed-pass-123", users=2)
    r = client.post("/api/v1/login", json={"username": "demo02", "password": "seed-pass-123"})
    assert r.status_code == 200


def test_login_metrics_increment_per_result(client, registered):
    ok0 = sample("resilience_auth_logins_total", result="success")
    ko0 = sample("resilience_auth_logins_total", result="failed")
    client.post("/api/v1/login", json={"username": registered, "password": PASSWORD})
    client.post("/api/v1/login", json={"username": registered, "password": "wrong-wrong"})
    assert sample("resilience_auth_logins_total", result="success") == ok0 + 1
    assert sample("resilience_auth_logins_total", result="failed") == ko0 + 1
