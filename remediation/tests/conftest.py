"""Fixtures partagées : tout l'extérieur est mocké (proxy Docker, Ansible, verify_tx, HTTP, horloge)."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

import httpx
import pytest
import yaml

from actions.docker_proxy import DockerProxy
from actions.runner import RunnerResult
from broker_helpers import capture_logs  # noqa: F401  (réexporté pour les tests)
from config import Settings
from decision import DecisionTable, load_decision_table, parse_decision_table
from engine import RemediationEngine, Services
from journal import Journal
from models import IncomingEvent
from timeline import Broker
from verify import VerifyResult

TOKEN = "t0ken-" + "x" * 32
TABLE_PATH = Path(__file__).resolve().parent.parent / "decision_table.yml"
T0 = datetime(2026, 10, 21, 9, 14, 35, tzinfo=timezone.utc)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class FakeClock:
    def __init__(self, start: datetime = T0) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


class FakeVerifier:
    """verify_tx simulé : `results` consommé dans l'ordre (le dernier est répété)."""

    def __init__(self, results: list[bool] | None = None, clock: FakeClock | None = None,
                 cost_s: float = 0.0) -> None:
        self.results = list(results if results is not None else [True])
        self.calls = 0
        self.clock = clock
        self.cost_s = cost_s

    async def run(self) -> VerifyResult:
        ok = self.results[min(self.calls, len(self.results) - 1)]
        self.calls += 1
        if self.clock and self.cost_s:
            self.clock.advance(self.cost_s)
        return VerifyResult(ok=ok, rc=0 if ok else 1, detail="fake")


class FakeRunner:
    """ansible-runner simulé : enregistre (playbook, extravars)."""

    def __init__(self, ok: bool = True, changed: bool | None = True) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.ok = ok
        self.changed = changed

    async def run_playbook(self, playbook: str, extravars: dict[str, Any], timeout: float | None = None):
        self.calls.append((playbook, dict(extravars)))
        return RunnerResult(ok=self.ok, rc=0 if self.ok else 2, changed=self.changed, detail="fake")


class FakeNetwork:
    """Mock HTTP unique : docker-socket-proxy, auth, loki. Enregistre toutes les requêtes."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.restart_status = 204
        self.auth_status = 200
        self.loki_values: list[list[str]] = [["1", "waf_blocked"]]

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        host, path = request.url.host, request.url.path
        if host == "docker-socket-proxy":
            if path == "/_ping":
                return httpx.Response(200, text="OK")
            if path == "/containers/json":
                svc = json.loads(request.url.params["filters"])["label"][0].split("=")[1]
                return httpx.Response(200, json=[{"Id": f"cid-{svc}"}])
            if path.endswith("/restart"):
                return httpx.Response(self.restart_status)
            return httpx.Response(404)
        if host == "auth" and path == "/internal/tighten-rate-limit":
            return httpx.Response(self.auth_status, json={"ok": True})
        if host == "loki":
            return httpx.Response(200, json={"data": {"result": [{"values": self.loki_values}]}})
        return httpx.Response(599, text="hôte non mocké")

    def paths(self, method: str | None = None) -> list[str]:
        return [r.url.path for r in self.requests if method is None or r.method == method]

    def docker_calls(self) -> list[tuple[str, str]]:
        return [(r.method, r.url.path) for r in self.requests if r.url.host == "docker-socket-proxy"]


def make_settings(**overrides: Any) -> Settings:
    base = dict(token=TOKEN, internal_token="internal-" + "y" * 16, db_path=":memory:",
                verify_retries=1, verify_interval_s=0.0, action_timeout_s=5.0)
    base.update(overrides)
    return Settings(**base)


def make_table(*, cooldown: int = 60, max_attempts: int = 3, dry_run: bool = False,
               mutate: Callable[[dict], None] | None = None) -> DecisionTable:
    data = yaml.safe_load(TABLE_PATH.read_text(encoding="utf-8"))
    data["defaults"].update(cooldown_seconds=cooldown, max_attempts=max_attempts, dry_run=dry_run)
    if mutate:
        mutate(data)
    return parse_decision_table(data)


def make_event(incident_type: str = "service_flood", *, service: str = "payment-api",
               source_ip: str | None = "203.0.113.7", ts: datetime = T0, event_id: str | None = None) -> IncomingEvent:
    payload: dict[str, Any] = {
        "service": service, "anomaly_score": 0.87, "threshold": 0.6, "incident_type": incident_type,
        "ts": ts.isoformat(), "source_ip": source_ip,
        "features_top": [{"name": "req_per_s", "value": 420.0, "z": 9.2}],
    }
    if event_id:
        payload["event_id"] = event_id
    return IncomingEvent.model_validate(payload)


class Env:
    """Banc d'essai complet autour d'un moteur réel et de dépendances factices."""

    def __init__(self, *, table: DecisionTable | None = None, verify: list[bool] | None = None,
                 settings: Settings | None = None, runner_ok: bool = True, verify_cost_s: float = 0.0) -> None:
        import asyncio

        self.clock = FakeClock()
        self.net = FakeNetwork()
        self.http = httpx.AsyncClient(transport=httpx.MockTransport(self.net.handler))
        self.settings = settings or make_settings()
        self.runner = FakeRunner(ok=runner_ok)
        self.verifier = FakeVerifier(verify, self.clock, verify_cost_s)
        self.journal = Journal(":memory:")
        self.broker = Broker()
        self.sleeps: list[float] = []

        async def fake_sleep(s: float) -> None:  # le temps est simulé : pas d'attente réelle
            self.sleeps.append(s)
            self.clock.advance(s)
            await asyncio.sleep(0)

        self.services = Services(
            http=self.http,
            docker=DockerProxy(self.http, self.settings.docker_proxy_url, self.settings.docker_allow_recreate),
            runner=self.runner, verifier=self.verifier)
        self.log = logging.getLogger("remediation-test")
        self.log.propagate = False
        self.engine = RemediationEngine(
            table=table or load_decision_table(TABLE_PATH), settings=self.settings, journal=self.journal,
            broker=self.broker, services=self.services, log=self.log, clock=self.clock, sleep=fake_sleep)

    async def run(self, event: IncomingEvent):
        sub = await self.engine.handle_event(event)
        if sub.decision == "started":
            await self.engine.wait(sub.incident_id)
        return sub

    def incident(self, incident_id: str) -> dict[str, Any]:
        inc = self.journal.get_incident(incident_id)
        assert inc is not None
        return inc

    def action_types(self, incident_id: str) -> list[str]:
        return [a["type"] for a in self.incident(incident_id)["actions"]]


@pytest.fixture
def make_env() -> Callable[..., Env]:
    return Env
