"""Contrats d'interface (docs/contracts.md) : logs §1, métriques §2, health/ready, erreurs."""

import re
import uuid

import pytest
from fastapi.testclient import TestClient
from paykit import bearer, make_token, sample
from resilience_db import Base, make_engine

from payment_api.main import create_app

MANDATORY = {"ts", "level", "service", "event", "message", "request_id"}
ISO_TS = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")
TX = "/api/v1/transactions"


def test_transaction_created_log_matches_contract_format(client, alice, log_lines):
    r = client.post(
        TX,
        headers={**alice, "X-Forwarded-For": "192.168.137.50"},
        json={"src_account": 1, "dst_account": 3, "amount_cents": 100},
    )
    (e,) = log_lines("transaction_created")
    assert MANDATORY <= set(e)
    assert ISO_TS.match(e["ts"]) and e["level"] == "INFO" and e["service"] == "payment-api"
    assert uuid.UUID(e["request_id"]) and e["request_id"] == r.headers["X-Request-ID"]
    assert e["user"] == "alice" and e["client_ip"] == "192.168.137.50"
    assert (e["http_method"], e["http_path"], e["http_status"]) == ("POST", TX, 201)
    assert isinstance(e["duration_ms"], int)
    assert "Authorization" not in str(e) and alice["Authorization"][7:] not in str(e)


def test_transaction_rejected_log_is_warning_with_reason(client, alice, log_lines):
    client.post(
        TX, headers=alice, json={"src_account": 2, "dst_account": 3, "amount_cents": 99_999}
    )
    (e,) = log_lines("transaction_rejected")
    assert e["level"] == "WARNING" and e["http_status"] == 409 and e["user"] == "alice"
    assert "insufficient_funds" in e["message"]


def test_all_emitted_events_belong_to_the_contract(client, alice, log_lines):
    client.post(TX, headers=alice, json={"src_account": 1, "dst_account": 3, "amount_cents": 100})
    client.post(
        TX, headers=alice, json={"src_account": 2, "dst_account": 3, "amount_cents": 99_999}
    )
    from resilience_common.logging import NORMALIZED_EVENTS

    events = {r["event"] for r in log_lines()}
    assert {"transaction_created", "transaction_rejected"} <= events
    assert {e for e in events if e != "log"} <= NORMALIZED_EVENTS


@pytest.fixture
def broken_client(settings, tmp_path):
    """App dont la base est injoignable (répertoire inexistant) : simule une panne DB."""
    engine = make_engine(f"sqlite:///{tmp_path}/missing-dir/x.db")
    return TestClient(create_app(settings, engine))


def test_db_error_emits_event_metric_and_503_contract_error(broken_client, log_lines):
    before = sample("resilience_db_errors_total")
    r = broken_client.get("/api/v1/accounts", headers=bearer(make_token("alice")))
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "db_unavailable"
    assert set(r.json()["error"]) == {"code", "message", "request_id"}
    assert sample("resilience_db_errors_total") == before + 1
    (e,) = log_lines("db_error")
    assert e["level"] == "ERROR" and e["http_status"] == 503 and e["service"] == "payment-api"
    assert "SELECT" not in e["message"]  # aucune requête SQL ne fuit dans les logs


def test_ready_is_503_when_db_down_but_health_stays_up_and_probe_is_not_counted(broken_client):
    before = sample("resilience_db_errors_total")
    assert broken_client.get("/health").status_code == 200
    r = broken_client.get("/ready")
    assert r.status_code == 503 and r.json()["error"]["code"] == "db_unavailable"
    assert sample("resilience_db_errors_total") == before


def test_health_and_ready_ok(client):
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/ready").json() == {"status": "ready"}


def test_request_id_is_propagated_only_if_uuid(client):
    rid = str(uuid.uuid4())
    assert client.get("/health", headers={"X-Request-ID": rid}).headers["X-Request-ID"] == rid
    forged = client.get("/health", headers={"X-Request-ID": 'x"}\n{"event":"forged"'})
    assert uuid.UUID(forged.headers["X-Request-ID"])


def test_unknown_route_uses_contract_error_body(client):
    r = client.get("/nope")
    assert r.status_code == 404 and r.json()["error"]["code"] == "http_404"


def test_metrics_endpoint_exposes_business_metrics_and_http_instrumentation(client, alice):
    client.get("/api/v1/accounts", headers=alice)
    text = client.get("/metrics").text
    assert "resilience_transactions_total" in text
    assert "resilience_db_errors_total" in text
    # instrumentation HTTP branchée via resilience_common.metrics.instrument(app, "payment-api")
    assert re.search(r'resilience_http_requests_total\{[^}]*path="/api/v1/accounts"', text)


def test_http_metrics_follow_contract_names_and_labels(client, alice):
    client.get("/api/v1/accounts", headers=alice)
    text = client.get("/metrics").text
    # Nom et labels du contrat §2 (ordre d'affichage alphabétique côté Prometheus).
    assert re.search(r'resilience_http_requests_total\{[^}]*service="payment-api"[^}]*\}', text)
    assert re.search(r'resilience_http_requests_total\{[^}]*path="/api/v1/accounts"[^}]*\}', text)
    assert "resilience_http_request_duration_seconds_bucket" in text


def test_docs_disabled_by_default(client):
    assert client.get("/docs").status_code == 404


def test_lifespan_runs_alembic_migrations(settings, tmp_path):
    from sqlalchemy import inspect

    from payment_api.config import Settings

    engine = make_engine(f"sqlite:///{tmp_path}/p.db")
    s = Settings(jwt_secret=settings.jwt_secret, run_migrations=True)
    with TestClient(create_app(s, engine)) as c:
        assert c.get("/ready").status_code == 200
    assert {"users", "accounts", "transactions"} <= set(inspect(engine).get_table_names())
    assert Base.metadata.tables.keys() <= set(inspect(engine).get_table_names())
