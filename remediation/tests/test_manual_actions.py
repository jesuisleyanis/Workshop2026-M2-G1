"""POST /manual-actions : action confirmée par un opérateur (liste blanche, garde-fous, journal, SSE)."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from actions.runner import PLAYBOOK_WAF_DENY
from conftest import TOKEN, Env, capture_logs, make_settings, make_table
from export_journal import export
from main import create_app

AUTH = {"Authorization": f"Bearer {TOKEN}"}


def _client(env: Env, **settings) -> TestClient:
    return TestClient(create_app(make_settings(**settings), table=env.engine.table, services=env.services))


@pytest.fixture
def env() -> Env:
    return Env(table=make_table(cooldown=0), verify=[True])


@pytest.fixture
def client(env):
    with _client(env) as c:
        yield c


def test_block_ip_success_journal_and_stream(client, env):
    with capture_logs("remediation") as logs:
        r = client.post("/manual-actions", headers=AUTH, json={
            "action": "waf_block_ip", "params": {"source": "203.0.113.9"}, "reason": "IP vue dans les logs"})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["action"] == "waf_block_ip" and out["status"] == "ok" and "203.0.113.9" in out["detail"]
    assert env.runner.calls == [(PLAYBOOK_WAF_DENY, {"deny_ip": "203.0.113.9", "deny_list": "temporary",
                                                     "incident_id": out["incident_id"]})]

    inc = client.get(f"/incidents/{out['incident_id']}", headers=AUTH).json()
    assert inc["incident_type"] == "manual_action" and inc["status"] == "closed"
    assert inc["reason"] == "IP vue dans les logs"
    assert [a["type"] for a in inc["actions"]] == ["waf_block_ip"]
    assert any(line["event"] == "remediation_manual_action" and line["incident_id"] == out["incident_id"]
               for line in logs)

    sse = client.get(f"/stream?follow=false&incident_id={out['incident_id']}", headers=AUTH).text
    frames = [json.loads(line[6:]) for line in sse.splitlines() if line.startswith("data: ")]
    assert [f["phase"] for f in frames] == ["decision", "action", "action", "closure"]
    assert all(f["incident_type"] == "manual_action" for f in frames)
    assert frames[0]["data"]["manual"] is True and frames[0]["data"]["reason"] == "IP vue dans les logs"


def test_restart_service_success(client, env):
    r = client.post("/manual-actions", headers=AUTH,
                    json={"action": "restart_service", "params": {"service": "payment-api"}})
    assert r.status_code == 200 and r.json()["status"] == "ok"
    assert ("POST", "/containers/cid-payment-api/restart") in env.net.docker_calls()


@pytest.mark.parametrize("body", [
    {"action": "restore_pg_dump", "params": {}},                    # hors liste blanche
    {"action": "waf_blacklist_ip", "params": {"source": "203.0.113.9"}},
    {"action": "waf_block_ip", "params": {"source": "from_event"}},  # IP littérale exigée
    {"action": "waf_block_ip", "params": {"source": "10.0.0.0/8"}},
    {"action": "waf_block_ip", "params": {"source": "1.2.3.4", "x": 1}},
    {"action": "restart_service", "params": {"service": "postgres"}},  # hors restartable_services
    {"action": "restart_service", "params": {"service": "../x"}},
    {"action": "waf_block_ip", "params": {"source": "1.2.3.4"}, "reason": "x" * 201},
])
def test_invalid_or_forbidden_is_422_and_nothing_runs(client, env, body):
    r = client.post("/manual-actions", headers=AUTH, json=body)
    assert r.status_code == 422 and "error" in r.json()
    assert env.runner.calls == [] and env.net.docker_calls() == []
    assert client.app.state.journal.list_incidents() == []


@pytest.mark.parametrize("ip", ["192.168.137.1", "127.0.0.1", "::1", " 127.0.0.1 ",
                                "::ffff:127.0.0.1", "::FFFF:192.168.137.1", "fe80::1%eth0"])
def test_protected_ip_is_refused(client, env, ip):
    r = client.post("/manual-actions", headers=AUTH, json={"action": "waf_block_ip", "params": {"source": ip}})
    assert r.status_code == 422 and r.json()["error"]["code"] == "action_refused"
    assert env.runner.calls == [] and client.app.state.journal.list_incidents() == []


def test_without_token_is_401(client, env):
    r = client.post("/manual-actions", json={"action": "waf_block_ip", "params": {"source": "203.0.113.9"}})
    assert r.status_code == 401 and r.json()["error"]["code"] == "unauthorized"
    assert env.runner.calls == []


def test_dry_run_executes_nothing(env):
    with _client(env, dry_run=True) as c:
        r = c.post("/manual-actions", headers=AUTH,
                   json={"action": "waf_block_ip", "params": {"source": "203.0.113.9"}})
        assert r.json()["status"] == "dry_run"
        assert c.get(f"/incidents/{r.json()['incident_id']}", headers=AUTH).json()["status"] == "dry_run"
    assert env.runner.calls == []


def test_manual_action_is_exported(env, tmp_path):
    db = tmp_path / "incidents.db"
    with _client(env, db_path=str(db)) as c:
        iid = c.post("/manual-actions", headers=AUTH, json={
            "action": "restart_service", "params": {"service": "auth"}, "reason": "test"}).json()["incident_id"]
    out = tmp_path / "incidents.json"
    assert export(str(db), str(out)) == 1
    inc = json.loads(out.read_text(encoding="utf-8"))["incidents"][0]
    assert inc["incident_id"] == iid and inc["incident_type"] == "manual_action"
    assert inc["actions"][0]["type"] == "restart_service"
