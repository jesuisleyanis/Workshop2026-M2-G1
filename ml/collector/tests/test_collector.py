"""Tests du collector avec un Prometheus simulé (httpx.MockTransport)."""

import asyncio

import httpx
import pytest
from fastapi.testclient import TestClient

from ml.collector.app import create_app
from ml.collector.collector import (
    CollectError,
    Collector,
    NoData,
    PrometheusClient,
    build_queries,
)
from ml.shared.features import FEATURE_NAMES

QUERIES = build_queries("30s")
BY_QUERY = {q: n for n, q in QUERIES.items()}


def prom_response(value):
    if value is None:
        return {"status": "success", "data": {"resultType": "vector", "result": []}}
    return {"status": "success", "data": {"resultType": "vector",
                                          "result": [{"metric": {}, "value": [1.0, str(value)]}]}}


def make_collector(values: dict, *, fail=False, interval=15.0) -> Collector:
    def handler(request: httpx.Request) -> httpx.Response:
        if fail:
            raise httpx.ConnectError("prometheus down")
        feature = BY_QUERY[request.url.params["query"]]
        return httpx.Response(200, json=prom_response(values.get(feature)))

    prom = PrometheusClient("http://prometheus:9090", transport=httpx.MockTransport(handler))
    return Collector(prom, queries=QUERIES, interval=interval)


def test_queries_cover_every_feature_with_contract_metrics():
    assert list(QUERIES) == list(FEATURE_NAMES)
    joined = " ".join(QUERIES.values())
    for metric in ("resilience_http_requests_total", "resilience_http_request_duration_seconds_bucket",
                   "resilience_auth_logins_total", "resilience_waf_blocked_total",
                   "resilience_db_errors_total", "container_cpu_usage_seconds_total",
                   "container_memory_working_set_bytes"):
        assert metric in joined


def test_auth_failed_counts_rate_limited_refusals_too():
    """Régression (capture réelle) : une force brute est vite refusée en 429 par le rate-limit,
    compté à part ; sans lui auth_failed_per_s retombait à ~0 et l'attaque était routée en
    service_flood (redémarrage de payment-api au lieu du blocage + rate-limit)."""
    q = QUERIES["auth_failed_per_s"]
    assert 'resilience_auth_logins_total{result="failed"}' in q
    assert "resilience_auth_rate_limited_total" in q
    assert q.count("or vector(0)") == 2  # un compteur encore sans série ne masque pas l'autre


@pytest.mark.parametrize("feature", ["cpu_pct_max", "mem_pct_max"])
def test_resource_features_only_look_at_platform_containers(feature):
    """La charge de l'observabilité (cAdvisor à 92 % de sa limite, compactions Prometheus) n'est
    pas un signal d'attaque : elle dominait mem_pct_max (91-99 % en continu dans la baseline)."""
    from ml.collector.collector import PLATFORM_SERVICES

    q = QUERIES[feature]
    assert 'name!=""' not in q
    selector = 'container_label_com_docker_compose_service=~"waf|front|payment-api|auth|postgres"'
    assert q.count(selector) == (2 if feature == "mem_pct_max" else 1)
    assert set(PLATFORM_SERVICES) == {"waf", "front", "payment-api", "auth", "postgres"}
    for excluded in ("cadvisor", "prometheus", "grafana", "loki"):
        assert excluded not in q


def test_collect_builds_vector_in_contract_order():
    values = {n: float(i + 1) for i, n in enumerate(FEATURE_NAMES)}
    snap = asyncio.run(make_collector(values).collect())
    assert snap.vector == [float(i + 1) for i in range(len(FEATURE_NAMES))]
    assert snap.missing == ()


def test_missing_features_filled_with_zero_and_reported():
    values = {"req_per_s": 12.0, "cpu_pct_max": 30.0}  # le reste : aucune série
    snap = asyncio.run(make_collector(values).collect())
    assert snap.vector[FEATURE_NAMES.index("req_per_s")] == 12.0
    assert snap.vector[FEATURE_NAMES.index("db_errors_per_s")] == 0.0
    assert "db_errors_per_s" in snap.missing and "req_per_s" not in snap.missing


def test_no_data_at_all_is_not_a_zero_vector():
    with pytest.raises(NoData):
        asyncio.run(make_collector({}).collect())


def test_nan_is_treated_as_missing():
    def handler(request):
        return httpx.Response(200, json=prom_response("NaN"))

    prom = PrometheusClient("http://p", transport=httpx.MockTransport(handler))
    with pytest.raises(NoData):
        asyncio.run(Collector(prom, queries=QUERIES).collect())


def test_prometheus_down_raises_and_tick_survives():
    c = make_collector({"req_per_s": 1.0}, fail=True)
    with pytest.raises(CollectError):
        asyncio.run(c.collect())
    assert asyncio.run(c.tick()) is None
    assert c.latest is None and c.fresh() is None
    assert c.collections_failed == 1 and "injoignable" in c.last_error


def test_last_snapshot_kept_but_goes_stale():
    c = make_collector({"req_per_s": 5.0})
    assert asyncio.run(c.tick()) is not None and c.fresh() is not None
    c.stale_after = -1  # tout snapshot est périmé
    assert c.fresh() is None and c.latest is not None


def test_http_api_features_ready_health_metrics():
    c = make_collector({n: 1.0 for n in FEATURE_NAMES})
    with TestClient(create_app(c, start_loop=False)) as client:
        assert client.get("/health").json() == {"status": "ok"}
        # pas encore de collecte -> 503 explicite, jamais de données inventées
        assert client.get("/ready").status_code == 503
        assert client.get("/api/v1/features").status_code == 503

        asyncio.run(c.tick())
        assert client.get("/ready").status_code == 200
        body = client.get("/api/v1/features").json()
        assert body["feature_names"] == list(FEATURE_NAMES)
        assert body["vector"] == [1.0] * len(FEATURE_NAMES) and body["ts"].endswith("Z")
        assert client.get("/metrics").status_code == 200


def test_each_collection_gets_an_increasing_sequence_number():
    c = make_collector({n: 1.0 for n in FEATURE_NAMES})
    first, second = asyncio.run(c.tick()), asyncio.run(c.tick())
    assert (first.seq, second.seq) == (1, 2) and second.to_json()["seq"] == 2


def test_long_poll_returns_as_soon_as_a_newer_collection_exists():
    c = make_collector({n: 1.0 for n in FEATURE_NAMES})

    async def scenario():
        await c.tick()  # seq 1
        waiter = asyncio.create_task(c.wait_newer(after=1, timeout=5.0))
        await asyncio.sleep(0.05)
        assert not waiter.done()  # rien de neuf : il attend
        loop = asyncio.get_running_loop()
        t0 = loop.time()
        await c.tick()  # seq 2 -> réveil immédiat
        snap = await waiter
        return snap, loop.time() - t0

    snap, waited = asyncio.run(scenario())
    assert snap.seq == 2 and waited < 0.5


def test_long_poll_times_out_with_the_current_snapshot():
    c = make_collector({n: 1.0 for n in FEATURE_NAMES})

    async def scenario():
        await c.tick()
        return await c.wait_newer(after=1, timeout=0.05)

    assert asyncio.run(scenario()).seq == 1


def test_http_long_poll_parameters_are_validated():
    c = make_collector({n: 1.0 for n in FEATURE_NAMES})
    with TestClient(create_app(c, start_loop=False)) as client:
        asyncio.run(c.tick())
        assert client.get("/api/v1/features", params={"after": 0, "wait": 1}).json()["seq"] == 1
        assert client.get("/api/v1/features", params={"wait": 60}).status_code == 422  # plafond 10 s
