"""Le JWT est exigé et validé sur TOUTES les routes métier (dépendance commune)."""

from datetime import timedelta

import pytest
from paykit import JWT_SECRET, bearer, make_token

PROTECTED = [
    ("GET", "/api/v1/accounts"),
    ("GET", "/api/v1/transactions"),
    ("POST", "/api/v1/transactions"),
]
BODY = {"src_account": 1, "dst_account": 3, "amount_cents": 100}


def _call(client, method, path, headers=None):
    return client.request(method, path, headers=headers, json=BODY if method == "POST" else None)


@pytest.mark.parametrize("method,path", PROTECTED)
def test_missing_token_is_401_with_contract_error(client, method, path):
    r = _call(client, method, path)
    assert r.status_code == 401
    assert r.headers["WWW-Authenticate"].startswith("Bearer")
    assert r.json()["error"]["code"] == "missing_token"
    assert set(r.json()["error"]) == {"code", "message", "request_id"}


@pytest.mark.parametrize("method,path", PROTECTED)
@pytest.mark.parametrize(
    "token,code",
    [
        ("not.a.jwt", "invalid_token"),
        (
            make_token(secret="another-secret-another-secret-0000"),
            "invalid_token",
        ),  # mauvaise signature
        (make_token(ttl=timedelta(seconds=-5)), "token_expired"),
        (make_token(sub=None), "invalid_token"),  # claim sub obligatoire
        (make_token(sub="ghost"), "invalid_token"),  # compte inexistant
    ],
)
def test_invalid_tokens_are_rejected(client, method, path, token, code):
    r = _call(client, method, path, bearer(token))
    assert r.status_code == 401
    assert r.json()["error"]["code"] == code


def test_alg_none_token_is_rejected(client):
    import base64
    import json

    def b64(d):
        return base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()

    forged = f"{b64({'alg': 'none', 'typ': 'JWT'})}.{b64({'sub': 'alice', 'exp': 4102444800})}."
    assert client.get("/api/v1/accounts", headers=bearer(forged)).status_code == 401


def test_non_bearer_scheme_is_rejected(client):
    r = client.get("/api/v1/accounts", headers={"Authorization": f"Basic {make_token()}"})
    assert r.status_code == 401


def test_valid_token_from_auth_service_is_accepted(client, alice):
    """Contrat JWT : HS256 + claim sub (exactement ce qu'émet services/auth)."""
    assert client.get("/api/v1/accounts", headers=alice).status_code == 200


def test_probes_do_not_require_auth(client):
    assert client.get("/health").status_code == 200
    assert client.get("/ready").status_code == 200


def test_secret_must_be_strong():
    from payment_api.config import Settings

    with pytest.raises(RuntimeError):
        Settings(jwt_secret=JWT_SECRET[:10])
