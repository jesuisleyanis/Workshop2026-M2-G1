"""Ré-authentification avant un gros virement (#51) : POST /api/v1/auth/step-up."""

from datetime import UTC, datetime, timedelta

import jwt
from authkit import JWT_SECRET, PASSWORD, sample

SU = "/api/v1/auth/step-up"


def _login(client, password=PASSWORD):
    return client.post("/api/v1/login", json={"username": "alice", "password": password})


def _claims(token):
    return jwt.decode(token, JWT_SECRET, algorithms=["HS256"])


def test_login_token_carries_auth_time(client, registered):
    claims = _claims(_login(client).json()["access_token"])
    assert abs(claims["auth_time"] - datetime.now(UTC).timestamp()) < 5


def test_step_up_reissues_a_token_with_fresh_auth_time(client, registered, log_lines):
    old = jwt.encode(
        {
            "sub": "alice",
            "iat": datetime.now(UTC) - timedelta(minutes=10),
            "exp": datetime.now(UTC) + timedelta(minutes=5),
            "auth_time": int((datetime.now(UTC) - timedelta(minutes=10)).timestamp()),
        },
        JWT_SECRET,
        algorithm="HS256",
    )
    r = client.post(SU, headers={"Authorization": f"Bearer {old}"}, json={"password": PASSWORD})
    assert r.status_code == 200
    fresh = _claims(r.json()["access_token"])
    assert fresh["sub"] == "alice" and fresh["auth_time"] > _claims(old)["auth_time"] + 500
    (e,) = log_lines("auth_step_up_success")
    assert e["user"] == "alice"


def test_wrong_password_is_a_failed_login_for_detection(client, registered, log_lines):
    token = _login(client).json()["access_token"]
    before = sample("resilience_auth_logins_total", result="failed")
    r = client.post(SU, headers={"Authorization": f"Bearer {token}"}, json={"password": "nope"})
    assert r.status_code == 401 and r.json()["error"]["code"] == "invalid_credentials"
    assert sample("resilience_auth_logins_total", result="failed") == before + 1, (
        "force brute visible"
    )
    assert len(log_lines("auth_step_up_failed")) == 1


def test_step_up_requires_a_valid_session(client, registered):
    # 3 essais max : le quota de /login (3/minute en test) s'applique avant tout contrôle.
    for headers in ({}, {"Authorization": "Bearer nope"}):
        r = client.post(SU, headers=headers, json={"password": PASSWORD})
        assert r.status_code == 401 and r.json()["error"]["code"] == "invalid_token"
    forged = jwt.encode({"sub": "alice", "exp": datetime.now(UTC) + timedelta(minutes=5)}, "x" * 40)
    r = client.post(SU, headers={"Authorization": f"Bearer {forged}"}, json={"password": PASSWORD})
    assert r.status_code == 401


def test_step_up_shares_the_login_budget(client, registered):
    token = _login(client).json()["access_token"]  # 1 essai sur 3 (quota de test)
    h = {"Authorization": f"Bearer {token}"}
    codes = [client.post(SU, headers=h, json={"password": "x"}).status_code for _ in range(2)]
    assert codes == [401, 401]
    assert client.post(SU, headers=h, json={"password": PASSWORD}).status_code == 429
    assert _login(client).status_code == 429, "un seul budget pour /login et /step-up"


def test_step_up_keeps_expiry_and_role_never_extends_the_session(client, registered):
    exp = datetime.now(UTC) + timedelta(minutes=3)
    token = jwt.encode(
        {"sub": "alice", "exp": exp, "role": "operator"}, JWT_SECRET, algorithm="HS256"
    )
    r = client.post(SU, headers={"Authorization": f"Bearer {token}"}, json={"password": PASSWORD})
    fresh = _claims(r.json()["access_token"])
    assert fresh["exp"] == int(exp.timestamp()) and fresh["role"] == "operator"
    assert r.json()["expires_in"] <= 180
