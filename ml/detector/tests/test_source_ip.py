"""IP source dominante (Loki) : requête par type, dominance, garde-fous, pannes."""

import asyncio

import httpx
import pytest
from resilience_common import IncidentType

from ml.detector.source_ip import LokiSourceResolver, build_query, dominant_ip


def sample(ip, n):
    return {"metric": {"client_ip": ip}, "value": [1700000000.0, str(n)]}


@pytest.mark.parametrize(
    ("incident_type", "fragment"),
    [
        (IncidentType.SERVICE_FLOOD, '{service="waf"} | json | __error__="" [30s]'),
        (IncidentType.AUTH_ABUSE, 'http_status=~"401|429"'),
        (IncidentType.WEB_ATTACK, 'http_status="403"'),
    ],
)
def test_query_counts_waf_lines_by_client_ip_with_a_type_filter(incident_type, fragment):
    query = build_query(incident_type, 30)
    assert query.startswith("sum by (client_ip) (count_over_time(") and fragment in query


def test_no_query_for_incidents_without_a_meaningful_source():
    # Corruption interne / signature floue : bloquer une IP n'aurait pas de sens.
    assert build_query(IncidentType.DATA_CORRUPTION, 30) is None
    assert build_query(IncidentType.UNKNOWN, 30) is None


def test_dominant_ip_needs_share_and_volume():
    assert dominant_ip([sample("10.1.1.9", 90), sample("10.1.1.2", 10)], 0.6, 5) == "10.1.1.9"
    assert dominant_ip([sample("10.1.1.9", 50), sample("10.1.1.2", 50)], 0.6, 5) is None  # pas de dominante
    assert dominant_ip([sample("10.1.1.9", 4)], 0.6, 5) is None  # trop peu de lignes
    assert dominant_ip([], 0.6, 5) is None


def test_internal_networks_are_never_candidates():
    # Trafic verify_tx de la remédiation (réseau app) + passerelle Docker : jamais désignés.
    from ml.detector.source_ip import parse_networks

    internal = parse_networks("172.30.0.0/24, 172.31.0.0/24")
    result = [sample("172.31.0.9", 80), sample("172.31.0.1", 50), sample("192.168.137.42", 30)]
    assert dominant_ip(result, 0.6, 5, internal) == "192.168.137.42"
    assert dominant_ip([sample("172.31.0.9", 80)], 0.6, 5, internal) is None


def test_dominant_ip_never_returns_a_non_ip_value():
    # Une valeur de log forgée ne doit jamais devenir une cible (elle finirait dans la conf Nginx).
    assert dominant_ip([sample("1.2.3.4; deny all", 99), sample("", 50)], 0.6, 5) is None
    assert dominant_ip([sample("::ffff:10.0.0.7", 30)], 0.6, 5) == "::ffff:a00:7"


def resolver(handler):
    return LokiSourceResolver("http://loki:3100/", transport=httpx.MockTransport(handler))


def test_resolver_queries_loki_instant_endpoint():
    seen = []

    def handler(request):
        seen.append(request)
        body = {"status": "success", "data": {"resultType": "vector", "result": [sample("192.168.137.42", 60)]}}
        return httpx.Response(200, json=body)

    assert asyncio.run(resolver(handler).resolve(IncidentType.AUTH_ABUSE)) == "192.168.137.42"
    assert seen[0].url.path == "/loki/api/v1/query"
    assert "401|429" in seen[0].url.params["query"]


@pytest.mark.parametrize(
    "response",
    [httpx.Response(503), httpx.Response(200, text="pas du json"), httpx.Response(200, json={"data": {}})],
)
def test_resolver_failure_yields_no_ip_never_an_exception(response):
    assert asyncio.run(resolver(lambda request: response).resolve(IncidentType.SERVICE_FLOOD)) is None


def test_resolver_skips_loki_for_types_without_source():
    def handler(request):  # pragma: no cover - ne doit pas être appelé
        raise AssertionError("aucune requête attendue")

    assert asyncio.run(resolver(handler).resolve(IncidentType.DATA_CORRUPTION)) is None
