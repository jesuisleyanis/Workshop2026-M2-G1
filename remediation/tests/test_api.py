"""API : authentification de /events (401 sans token), cycle complet, SSE, sondes, métriques."""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from conftest import TOKEN, Env, make_event, make_settings, make_table
from main import create_app

AUTH = {"Authorization": f"Bearer {TOKEN}"}


def body(event_type: str = "data_corruption", **kw) -> dict:
    ev = make_event(event_type, ts=datetime.now(timezone.utc), **{"source_ip": None, **kw})
    return json.loads(ev.model_dump_json())


@pytest.fixture
def env() -> Env:
    return Env(table=make_table(cooldown=0), verify=[True])


@pytest.fixture
def client(env):
    app = create_app(make_settings(), table=env.engine.table, services=env.services)
    with TestClient(app) as c:
        c.env = env
        yield c


def wait_closed(client: TestClient, incident_id: str, timeout: float = 5.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        inc = client.get(f"/incidents/{incident_id}", headers=AUTH).json()
        if inc["status"] != "in_progress":
            return inc
        time.sleep(0.02)
    raise AssertionError("incident non terminé")


# ------------------------------------------------------------------ authentification
def test_post_events_without_token_is_401(client):
    r = client.post("/events", json=body())
    assert r.status_code == 401
    assert r.headers["www-authenticate"] == "Bearer"
    err = r.json()["error"]  # corps d'erreur du contrat
    assert err["code"] == "unauthorized" and err["request_id"]
    assert client.env.runner.calls == [] and client.app.state.journal.list_incidents() == []


@pytest.mark.parametrize("headers", [
    {"Authorization": "Bearer wrong-token-wrong-token-wrong"},
    {"Authorization": f"Basic {TOKEN}"},
    {"Authorization": TOKEN},
    {"Authorization": "Bearer "},
    {"X-Remediation-Token": TOKEN},  # pas d'en-tête alternatif
])
def test_post_events_with_bad_credentials_is_401(client, headers):
    assert client.post("/events", json=body(), headers=headers).status_code == 401
    assert client.app.state.journal.list_incidents() == []


def test_token_in_query_string_is_not_accepted(client):
    assert client.post(f"/events?token={TOKEN}", json=body()).status_code == 401


@pytest.mark.parametrize("method,path", [
    ("get", "/stream?follow=false"), ("get", "/incidents"), ("get", "/incidents/abc"), ("get", "/decision-table"),
])
def test_every_non_probe_route_requires_the_token(client, method, path):
    assert getattr(client, method)(path).status_code == 401
    assert getattr(client, method)(path, headers=AUTH).status_code != 401


def test_fail_closed_when_token_not_configured(env):
    app = create_app(make_settings(token=None), table=env.engine.table, services=env.services)
    with TestClient(app) as c:
        assert c.post("/events", json=body(), headers=AUTH).status_code == 503
        assert c.get("/ready").status_code == 503
    short = create_app(make_settings(token="short"), table=env.engine.table, services=env.services)
    with TestClient(short) as c:
        assert c.post("/events", json=body(), headers={"Authorization": "Bearer short"}).status_code == 503


# ------------------------------------------------------------------ cycle de bout en bout
def test_authenticated_event_runs_remediation_and_closes_incident(client):
    r = client.post("/events", json=body("data_corruption"), headers=AUTH)
    assert r.status_code == 202
    data = r.json()
    assert data["decision"] == "started" and data["dry_run"] is False

    inc = wait_closed(client, data["incident_id"])
    assert inc["status"] == "closed" and inc["incident_type"] == "data_corruption"
    assert inc["mttr_seconds"] is not None and inc["mttd_seconds"] is not None
    assert [a["type"] for a in inc["actions"]] == ["restore_pg_dump"]
    assert client.env.runner.calls[0][0] == "pg_restore.yml"
    assert client.get("/incidents", headers=AUTH).json()["incidents"][0]["incident_id"] == data["incident_id"]


def test_invalid_event_is_rejected_with_contract_error_body(client):
    bad = body()
    bad["incident_type"] = "ransomware"  # hors énumération figée
    r = client.post("/events", json=bad, headers=AUTH)
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_request"

    inj = body("service_flood")
    inj["source_ip"] = "1.2.3.4; deny all"  # doit finir dans une conf Nginx -> refusé
    assert client.post("/events", json=inj, headers=AUTH).status_code == 422


def test_unknown_incident_returns_404(client):
    r = client.get("/incidents/nope", headers=AUTH)
    assert r.status_code == 404 and r.json()["error"]["code"] == "incident_not_found"


def test_decision_table_endpoint_serves_the_loaded_file(client):
    t = client.get("/decision-table", headers=AUTH).json()
    assert t["version"] == "1.0" and len(t["rules"]) == 5


# ------------------------------------------------------------------ SSE
def parse_sse(text: str) -> list[dict]:
    out = []
    for block in text.split("\n\n"):
        fields = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line and not line.startswith(":"))
        if "data" in fields:
            out.append({"id": int(fields["id"]), "event": fields["event"], "data": json.loads(fields["data"])})
    return out


def test_stream_replays_timeline_as_sse_and_supports_last_event_id(client):
    inc_id = client.post("/events", json=body("data_corruption"), headers=AUTH).json()["incident_id"]
    wait_closed(client, inc_id)

    r = client.get("/stream?follow=false&since=0", headers=AUTH)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    assert r.headers["cache-control"] == "no-cache"
    events = parse_sse(r.text)
    assert {e["event"] for e in events} == {"timeline"}
    assert [e["data"]["phase"] for e in events][:2] == ["detection", "decision"]
    assert events[-1]["data"]["phase"] == "closure"
    assert all(e["data"]["incident_id"] == inc_id for e in events)

    # reconnexion : Last-Event-ID ne rejoue que la suite
    mid = events[1]["id"]
    resumed = parse_sse(client.get("/stream?follow=false", headers={**AUTH, "Last-Event-ID": str(mid)}).text)
    assert [e["id"] for e in resumed] == [e["id"] for e in events if e["id"] > mid]

    other = parse_sse(client.get("/stream?follow=false&since=0&incident_id=autre", headers=AUTH).text)
    assert other == []


# ------------------------------------------------------------------ sondes / métriques
def test_health_ready_without_auth(client):
    assert client.get("/health").json() == {"status": "ok"}
    r = client.get("/ready")
    assert r.status_code == 200 and r.json()["checks"]["docker_socket_proxy"] is True


def test_ready_is_503_when_docker_socket_proxy_is_down(env):
    env.net.handler_original = env.net.handler
    app = create_app(make_settings(), table=env.engine.table, services=env.services)
    env.services.docker.ping = _false  # type: ignore[method-assign]
    with TestClient(app) as c:
        r = c.get("/ready")
        assert r.status_code == 503 and r.json()["checks"]["docker_socket_proxy"] is False


async def _false() -> bool:
    return False


def test_metrics_endpoint_exposes_contract_metrics(env):
    app = create_app(make_settings(), table=env.engine.table, services=env.services)
    with TestClient(app) as c:
        inc_id = c.post("/events", json=body("data_corruption"), headers=AUTH).json()["incident_id"]
        wait_closed(c, inc_id)
        text = c.get("/metrics").text
    assert 'resilience_remediation_actions_total{action="restore_pg_dump",result="success"}' in text
    assert f'resilience_mttr_seconds{{incident_id="{inc_id}"}}' in text
    assert f'resilience_mttd_seconds{{incident_id="{inc_id}"}}' in text
    assert 'resilience_http_requests_total{method="POST",path="/events",service="remediation",status="202"}' in text
    assert "resilience_http_request_duration_seconds_bucket" in text
    # Une seule déclaration dans le registre (régression : DuplicateTimeseries au boot quand
    # http_metrics redéclarait le compteur déjà enregistré par resilience_common).
    assert text.count("# HELP resilience_http_requests_total ") == 1
