"""Rate-limit /login, resserrage par la remédiation, API interne protégée."""

import pytest
from authkit import INTERNAL_TOKEN, sample

LOGIN = "/api/v1/login"
BAD = {"username": "alice", "password": "wrong-wrong"}
HDR = {"X-Internal-Token": INTERNAL_TOKEN}


def _hammer(client, n, headers=None, body=BAD):
    return [client.post(LOGIN, json=body, headers=headers).status_code for _ in range(n)]


def test_login_is_rate_limited_with_429_after_threshold(client, registered):
    codes = _hammer(client, 5)  # limite de test : 3/minute
    assert codes == [401, 401, 401, 429, 429]


def test_rate_limit_emits_event_log_and_metric_and_contract_error(client, registered, log_lines):
    before = sample("resilience_auth_rate_limited_total")
    _hammer(client, 3)
    r = client.post(LOGIN, json=BAD)
    assert r.status_code == 429
    assert r.json()["error"]["code"] == "rate_limited"
    assert r.headers["Retry-After"] == "60"
    assert sample("resilience_auth_rate_limited_total") == before + 1
    (entry,) = log_lines("auth_rate_limited")
    assert entry["level"] == "WARNING" and entry["http_status"] == 429
    assert entry["service"] == "auth" and entry["request_id"] == r.headers["X-Request-ID"]


def test_rate_limit_is_per_client_ip(client, registered):
    assert _hammer(client, 4, headers={"X-Forwarded-For": "10.0.0.1"})[-1] == 429
    assert _hammer(client, 1, headers={"X-Forwarded-For": "10.0.0.2"}) == [
        401
    ]  # autre IP : intacte


def test_spoofed_leftmost_xff_cannot_evade_rate_limit(client, registered):
    """Seule l'entrée ajoutée par le proxy de confiance (la plus à droite) compte."""
    codes = [
        client.post(
            LOGIN, json=BAD, headers={"X-Forwarded-For": f"6.6.6.{i}, 10.9.9.9"}
        ).status_code
        for i in range(4)
    ]
    assert codes[-1] == 429


def test_tighten_requires_internal_token(client):
    assert client.post("/internal/tighten-rate-limit", json={"factor": 0.5}).status_code == 401
    r = client.post(
        "/internal/tighten-rate-limit", json={"factor": 0.5}, headers={"X-Internal-Token": "bad"}
    )
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "invalid_internal_token"


def test_tighten_reduces_limit_by_factor_and_applies_immediately(client, registered):
    r = client.post("/internal/tighten-rate-limit", json={"factor": 0.5}, headers=HDR)
    assert r.status_code == 200
    assert r.json() == {"previous_limit": "3/minute", "current_limit": "1/minute"}  # floor(3*0.5)=1
    assert _hammer(client, 3) == [401, 429, 429]


def test_tighten_never_goes_below_one_per_period(client):
    for _ in range(4):
        r = client.post("/internal/tighten-rate-limit", json={"factor": 0.1}, headers=HDR)
    assert r.json()["current_limit"] == "1/minute"


@pytest.mark.parametrize("factor", [0, -1, 1.5, "x"])
def test_tighten_rejects_invalid_factor(client, factor):
    assert (
        client.post(
            "/internal/tighten-rate-limit", json={"factor": factor}, headers=HDR
        ).status_code
        == 422
    )


def test_reset_restores_baseline_limit(client):
    client.post("/internal/tighten-rate-limit", json={"factor": 0.1}, headers=HDR)
    r = client.post("/internal/reset-rate-limit", headers=HDR)
    assert r.json() == {"previous_limit": "1/minute", "current_limit": "3/minute"}
    assert client.post("/internal/reset-rate-limit").status_code == 401


def test_register_is_rate_limited_after_threshold(client):
    """/register est borné (anti-flood de comptes, DoS bcrypt, énumération) — défaut 10/minute."""
    from authkit import PASSWORD

    codes = [
        client.post(
            "/api/v1/register", json={"username": f"u{i:02d}", "password": PASSWORD}
        ).status_code
        for i in range(12)
    ]
    assert codes[:10] == [201] * 10
    assert codes[10] == 429 and codes[11] == 429
    r = client.post("/api/v1/register", json={"username": "u99", "password": PASSWORD})
    assert r.json()["error"]["code"] == "rate_limited"
