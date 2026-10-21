"""GET /api/v1/status (#42) : état public du service pour le bandeau client."""

import re
import threading
import time

import pytest
from fastapi.testclient import TestClient
from paykit import JWT_SECRET
from resilience_db import make_engine

from payment_api.config import Settings
from payment_api.main import create_app
from payment_api.status import StatusCache

STATUS = "/api/v1/status"
ISO_Z = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


class FakeClock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


def _client(engine, clock=None) -> TestClient:
    settings = Settings(jwt_secret=JWT_SECRET, run_migrations=False)
    return TestClient(create_app(settings, engine, clock=clock or FakeClock()))


def test_status_ok_without_authentication(client):
    r = client.get(STATUS)
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"status", "checked_at"}, "aucun détail interne exposé"
    assert body["status"] == "ok" and ISO_Z.match(body["checked_at"])


def test_status_degraded_when_database_unreachable_without_leak(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path}/missing-dir/x.db")
    r = _client(engine).get(STATUS)
    assert r.status_code == 503
    assert set(r.json()) == {"status", "checked_at"} and r.json()["status"] == "degraded"
    for leak in ("sqlite", "OperationalError", "missing-dir", "version", "hostname"):
        assert leak not in r.text


def test_status_is_cached_so_traffic_cannot_amplify_into_the_database(engine, world, monkeypatch):
    clock = FakeClock()
    client = _client(engine, clock)
    calls = []
    real_connect = engine.connect

    def counting_connect(*a, **kw):
        calls.append(1)
        return real_connect(*a, **kw)

    monkeypatch.setattr(engine, "connect", counting_connect)
    first = client.get(STATUS).json()
    for _ in range(20):
        assert client.get(STATUS).json() == first
    assert len(calls) == 1, "une seule requête BDD par fenêtre de cache"
    clock.t += 2.5
    client.get(STATUS)
    assert len(calls) == 2, "le cache expire après STATUS_CACHE_S"


def test_status_recovers_after_cache_window(tmp_path):
    clock = FakeClock()
    db_dir = tmp_path / "later"
    client = _client(make_engine(f"sqlite:///{db_dir}/x.db"), clock)
    assert client.get(STATUS).status_code == 503
    db_dir.mkdir()
    assert client.get(STATUS).status_code == 503, "toujours servi depuis le cache"
    clock.t += 2.5
    assert client.get(STATUS).json()["status"] == "ok"


@pytest.mark.parametrize("method", ["post", "put", "delete"])
def test_status_is_read_only(client, method):
    assert getattr(client, method)(STATUS).status_code == 405


def test_concurrent_cache_misses_run_a_single_probe_and_serve_stale_meanwhile():
    clock = FakeClock()
    calls, gate = [], threading.Event()

    def slow_probe() -> bool:
        calls.append(1)
        if len(calls) > 1:
            gate.wait(2)  # BDD qui pend pendant le rafraîchissement
        return True

    cache = StatusCache(slow_probe, 2.0, clock)
    first = cache.get()
    clock.t += 3
    results: list = []
    threads = [threading.Thread(target=lambda: results.append(cache.get())) for _ in range(20)]
    for t in threads:
        t.start()
    time.sleep(0.2)
    assert len(calls) == 2, "un seul rafraîchissement malgré 20 requêtes simultanées"
    assert len(results) == 19 and all(r is first for r in results), (
        "les autres servent la valeur connue"
    )
    gate.set()
    for t in threads:
        t.join()


def test_status_probe_is_not_counted_in_ml_http_metrics(client):
    from paykit import sample

    before = sample(
        "resilience_http_requests_total",
        service="payment-api",
        method="GET",
        path="/api/v1/status",
        status="200",
    )
    client.get(STATUS)
    after = sample(
        "resilience_http_requests_total",
        service="payment-api",
        method="GET",
        path="/api/v1/status",
        status="200",
    )
    assert before == after == 0, "sonde exclue des features ML, comme /ready"


@pytest.mark.parametrize("value", [0.0, -1.0, 0.1, 120.0])
def test_status_cache_window_is_bounded(value):
    with pytest.raises(RuntimeError, match="STATUS_CACHE_S"):
        Settings(jwt_secret=JWT_SECRET, status_cache_s=value)
