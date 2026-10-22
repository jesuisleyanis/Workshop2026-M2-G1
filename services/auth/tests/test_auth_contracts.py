"""Contrats d'interface (docs/contracts.md) : logs §1, métriques §2, health/erreurs, config."""

import re
import uuid

import pytest
from authkit import INTERNAL_TOKEN, JWT_SECRET, PASSWORD
from fastapi.testclient import TestClient
from resilience_db import make_engine

from auth_service.config import Settings
from auth_service.main import create_app

MANDATORY = {"ts", "level", "service", "event", "message", "request_id"}
ISO_TS = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")


def _login(client, password, headers=None):
    return client.post(
        "/api/v1/login", json={"username": "alice", "password": password}, headers=headers
    )


def test_login_success_log_matches_contract_format(waf_client, registered, log_lines):
    r = _login(waf_client, PASSWORD, {"X-Forwarded-For": "192.168.137.50"})
    (e,) = log_lines("auth_login_success")
    assert MANDATORY <= set(e)
    assert ISO_TS.match(e["ts"]) and e["level"] == "INFO" and e["service"] == "auth"
    assert uuid.UUID(e["request_id"]) and e["request_id"] == r.headers["X-Request-ID"]
    assert e["user"] == "alice" and e["client_ip"] == "192.168.137.50"
    assert (e["http_method"], e["http_path"], e["http_status"]) == ("POST", "/api/v1/login", 200)
    assert isinstance(e["duration_ms"], int)


def test_login_failed_log_is_warning_and_never_contains_password(client, registered, log_lines):
    _login(client, "super-secret-wrong")
    (e,) = log_lines("auth_login_failed")
    assert e["level"] == "WARNING" and e["http_status"] == 401 and e["user"] == "alice"
    assert "super-secret-wrong" not in str(e) and PASSWORD not in str(e)


def test_all_emitted_events_belong_to_the_contract(client, registered, log_lines):
    _login(client, PASSWORD)
    _login(client, "wrong-wrong")
    for _ in range(4):
        _login(client, "wrong-wrong")
    from resilience_common.logging import NORMALIZED_EVENTS

    events = {r["event"] for r in log_lines()}
    assert {"auth_login_success", "auth_login_failed", "auth_rate_limited"} <= events
    assert {e for e in events if e != "log"} <= NORMALIZED_EVENTS


def test_request_id_is_propagated_only_if_uuid(client):
    rid = str(uuid.uuid4())
    assert client.get("/health", headers={"X-Request-ID": rid}).headers["X-Request-ID"] == rid
    forged = client.get("/health", headers={"X-Request-ID": 'x"}\n{"event":"forged"'})
    assert uuid.UUID(forged.headers["X-Request-ID"])  # remplacé par un uuid4 frais


def test_health_and_ready_ok(client):
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/ready").status_code == 200


def test_ready_is_503_when_db_unreachable(settings, tmp_path):
    broken = make_engine(f"sqlite:///{tmp_path}/missing-dir/x.db")
    c = TestClient(create_app(settings, broken))
    assert c.get("/health").status_code == 200  # liveness indépendante de la DB
    r = c.get("/ready")
    assert r.status_code == 503 and r.json()["error"]["code"] == "db_unavailable"


def test_db_failure_on_business_route_returns_503_contract_error(settings, tmp_path):
    broken = make_engine(f"sqlite:///{tmp_path}/missing-dir/x.db")
    c = TestClient(create_app(settings, broken))
    r = _login(c, PASSWORD)
    assert r.status_code == 503
    assert set(r.json()["error"]) == {"code", "message", "request_id"}


def test_unknown_route_uses_contract_error_body(client):
    r = client.get("/nope")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "http_404"


def test_metrics_endpoint_exposes_business_metrics_and_http_instrumentation(client, registered):
    _login(client, PASSWORD)
    text = client.get("/metrics").text
    assert "resilience_auth_logins_total" in text
    assert "resilience_auth_rate_limited_total" in text
    # instrumentation HTTP branchée via resilience_common.metrics.instrument(app, "auth")
    assert re.search(r'resilience_http_requests_total\{[^}]*path="/api/v1/login"', text)


def test_http_metrics_follow_contract_names_and_labels(client):
    client.get("/api/v1/login")
    text = client.get("/metrics").text
    # Nom et labels du contrat §2 (ordre d'affichage alphabétique côté Prometheus).
    assert re.search(r'resilience_http_requests_total\{[^}]*service="auth"[^}]*\}', text)
    assert re.search(r'resilience_http_requests_total\{[^}]*path="[^"]+"[^}]*\}', text)
    assert "resilience_http_request_duration_seconds_bucket" in text


def test_docs_disabled_by_default(client):
    assert client.get("/docs").status_code == 404
    assert client.get("/openapi.json").status_code == 404


def test_lifespan_runs_alembic_migrations(tmp_path):
    from sqlalchemy import inspect

    engine = make_engine(f"sqlite:///{tmp_path}/a.db")
    settings = Settings(jwt_secret=JWT_SECRET, internal_token=INTERNAL_TOKEN, run_migrations=True)
    with TestClient(create_app(settings, engine)) as c:
        assert c.get("/ready").status_code == 200
    assert {"users", "accounts", "transactions"} <= set(inspect(engine).get_table_names())


@pytest.mark.parametrize(
    "kwargs",
    [
        {"jwt_secret": "short", "internal_token": INTERNAL_TOKEN},
        {"jwt_secret": JWT_SECRET, "internal_token": "short"},
        {
            "jwt_secret": JWT_SECRET,
            "internal_token": INTERNAL_TOKEN,
            "login_rate_limit": "ten per minute",
        },
    ],
)
def test_settings_refuse_weak_or_invalid_config(kwargs):
    with pytest.raises(RuntimeError):
        Settings(**kwargs)


def test_settings_require_secrets_from_env(monkeypatch):
    for var in ("JWT_SECRET", "JWT_SECRET_FILE", "INTERNAL_TOKEN", "INTERNAL_TOKEN_FILE"):
        monkeypatch.delenv(var, raising=False)
    with pytest.raises(RuntimeError):
        Settings.from_env()
