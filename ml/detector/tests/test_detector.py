"""Tests du detector : score, seuil, AnomalyEvent conforme au schéma, POST remédiation mocké."""

import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient
from prometheus_client import REGISTRY

from resilience_common import AnomalyEvent, IncidentType
from resilience_common.events import SCHEMA_VERSION

from ml.detector.app import Runtime, create_app
from ml.detector.core import Detector, RemediationClient
from ml.detector.model import LoadedModel, ModelLoadError, load_model
from ml.shared.features import FEATURE_NAMES, vector_from_dict
from ml.training.train import save, train

TOKEN = "s3cr3t-test-token"
URL = "http://remediation:8005/events"


@pytest.fixture(scope="module")
def model_dir(tmp_path_factory):
    d = tmp_path_factory.mktemp("artifacts")
    model, stats = train(n_samples=6000, seed=11, version="test", n_estimators=100)
    save(model, stats, d)
    return d


@pytest.fixture(scope="module")
def loaded(model_dir) -> LoadedModel:
    return load_model(model_dir)


def normal_vector(loaded) -> list[float]:
    return vector_from_dict(loaded.stats["mean"])


def flood_vector(loaded) -> list[float]:
    d = dict(loaded.stats["mean"])
    d.update(req_per_s=420.0, ratio_5xx=0.34, p95_latency_ms=4000.0, cpu_pct_max=97.0)
    return vector_from_dict(d)


class FakeRemediation:
    """Capture les requêtes POST faites par RemediationClient (transport httpx simulé)."""

    def __init__(self, status=202):
        self.requests: list[httpx.Request] = []
        self.status = status
        self.client = RemediationClient(URL, TOKEN, retries=2, backoff=0,
                                        transport=httpx.MockTransport(self._handle))

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(self.status, json={"accepted": self.status < 400})


def make_detector(loaded, fake: FakeRemediation, clock=None, **kw) -> Detector:
    kwargs = dict(cooldown=60.0, **kw)
    if clock:
        kwargs["clock"] = clock
    return Detector(loaded, fake.client, **kwargs)


# --- au-dessus / en-dessous du seuil --------------------------------------------


def test_above_threshold_posts_schema_valid_event(loaded):
    fake = FakeRemediation()
    det = make_detector(loaded, fake)
    decision = asyncio.run(det.process(flood_vector(loaded)))

    assert decision.is_anomaly and decision.trigger == "model" and decision.posted
    assert len(fake.requests) == 1
    req = fake.requests[0]
    assert str(req.url) == URL and req.method == "POST"
    assert req.headers["authorization"] == f"Bearer {TOKEN}"

    payload = json.loads(req.content)
    event = AnomalyEvent.model_validate(payload)  # validation contre le schéma PARTAGÉ
    assert event.schema_version == SCHEMA_VERSION == payload["schema_version"]
    assert event.source == "detector" and event.service == "payment-api"
    assert event.incident_type is IncidentType.SERVICE_FLOOD
    assert event.anomaly_score >= event.threshold == pytest.approx(loaded.threshold, abs=1e-4)
    assert 0.0 < event.anomaly_score <= 1.0
    # features_top : dominantes d'abord, avec z-score
    names = [f.name for f in event.features_top]
    assert {"req_per_s", "ratio_5xx"} <= set(names) and len(names) <= 3
    zs = [abs(f.z) for f in event.features_top]
    assert zs == sorted(zs, reverse=True) and all(z >= 2.0 for z in zs)
    assert event.evidence.prometheus_query and event.evidence.loki_query
    # clés conformes au contrat §3
    assert set(payload) == {"schema_version", "event_id", "ts", "source", "service",
                            "anomaly_score", "threshold", "incident_type",
                            "features_top", "evidence"}
    assert payload["incident_type"] == "service_flood"


def test_below_threshold_emits_nothing(loaded):
    fake = FakeRemediation()
    det = make_detector(loaded, fake)
    decision = asyncio.run(det.process(normal_vector(loaded)))
    assert not decision.is_anomaly and decision.event is None and not decision.posted
    assert decision.score < decision.threshold
    assert fake.requests == []


def test_incident_type_routing_end_to_end(loaded):
    cases = {
        "auth_abuse": dict(auth_failed_per_s=40.0, ratio_4xx=0.5),
        "web_attack": dict(waf_blocked_per_s=30.0, ratio_4xx=0.4),
        "data_corruption": dict(db_errors_per_s=10.0, ratio_5xx=0.5),
    }
    for expected, patch in cases.items():
        fake = FakeRemediation()
        det = make_detector(loaded, fake)
        vec = vector_from_dict({**loaded.stats["mean"], **patch})
        asyncio.run(det.process(vec))
        event = AnomalyEvent.model_validate(json.loads(fake.requests[0].content))
        assert event.incident_type.value == expected


def test_cooldown_dedupes_persistent_anomaly(loaded):
    now = [0.0]
    fake = FakeRemediation()
    det = make_detector(loaded, fake, clock=lambda: now[0])
    vec = flood_vector(loaded)
    asyncio.run(det.process(vec))
    now[0] = 15.0
    d2 = asyncio.run(det.process(vec))
    assert d2.is_anomaly and d2.event is None and len(fake.requests) == 1
    now[0] = 61.0
    asyncio.run(det.process(vec))
    assert len(fake.requests) == 2


def test_failed_post_does_not_start_cooldown(loaded):
    fake = FakeRemediation(status=503)
    det = make_detector(loaded, fake)
    d1 = asyncio.run(det.process(flood_vector(loaded)))
    assert d1.event is not None and not d1.posted
    assert len(fake.requests) == 2  # 1 + 1 retry (retries=2)
    asyncio.run(det.process(flood_vector(loaded)))
    assert len(fake.requests) == 4  # réessaye au tick suivant


def test_auth_error_is_not_retried(loaded):
    fake = FakeRemediation(status=401)
    det = make_detector(loaded, fake)
    asyncio.run(det.process(flood_vector(loaded)))
    assert len(fake.requests) == 1


def test_missing_token_never_posts(loaded):
    rem = RemediationClient(URL, None, transport=httpx.MockTransport(lambda r: pytest.fail("POST")))
    det = Detector(loaded, rem)
    d = asyncio.run(det.process(flood_vector(loaded)))
    assert d.is_anomaly and not d.posted


def test_score_gauge_exposed_with_service_label(loaded):
    det = make_detector(loaded, FakeRemediation(), service="payment-api")
    d = asyncio.run(det.process(normal_vector(loaded)))
    value = REGISTRY.get_sample_value("resilience_anomaly_score", {"service": "payment-api"})
    assert value == pytest.approx(d.score)


def test_guardrail_catches_lone_extreme_spike_the_model_dilutes(loaded):
    fake = FakeRemediation()
    det = make_detector(loaded, fake)
    vec = vector_from_dict({**loaded.stats["mean"], "req_per_s": 600.0})
    d = asyncio.run(det.process(vec))
    assert d.score < d.threshold  # le modèle seul ne le voit pas
    assert d.trigger == "guardrail" and d.posted
    event = AnomalyEvent.model_validate(json.loads(fake.requests[0].content))
    assert event.incident_type is IncidentType.SERVICE_FLOOD
    assert event.features_top[0].name == "req_per_s"


def test_guardrail_never_fires_on_normal_traffic(loaded):
    from ml.training.dataset import generate_baseline

    fake = FakeRemediation()
    det = make_detector(loaded, fake)
    for row in generate_baseline(500, seed=2024):
        assert not asyncio.run(det.process(list(row))).is_anomaly
    assert fake.requests == []


# --- chargement du modèle -------------------------------------------------------


def test_load_model_rejects_tampered_artifact(model_dir, tmp_path):
    for f in ("model.joblib", "baseline_stats.json"):
        (tmp_path / f).write_bytes((model_dir / f).read_bytes())
    (tmp_path / "model.joblib").write_bytes(b"not the trained model")
    with pytest.raises(ModelLoadError, match="sha256"):
        load_model(tmp_path)


def test_load_model_missing_dir(tmp_path):
    with pytest.raises(ModelLoadError):
        load_model(tmp_path / "nope")


def test_load_model_rejects_feature_mismatch(model_dir, tmp_path):
    stats = json.loads((model_dir / "baseline_stats.json").read_text())
    stats["feature_names"] = list(reversed(FEATURE_NAMES))
    (tmp_path / "baseline_stats.json").write_text(json.dumps(stats))
    (tmp_path / "model.joblib").write_bytes((model_dir / "model.joblib").read_bytes())
    with pytest.raises(ModelLoadError, match="feature_names"):
        load_model(tmp_path)


# --- HTTP : collector -> detector -> remédiation --------------------------------


def make_runtime(loaded, features_status=200, vector=None):
    fake = FakeRemediation()
    det = make_detector(loaded, fake)

    def collector(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/features"
        if features_status != 200:
            return httpx.Response(features_status, json={"error": {"code": "no_fresh_data"}})
        return httpx.Response(200, json={"feature_names": list(FEATURE_NAMES), "vector": vector})

    http = httpx.AsyncClient(transport=httpx.MockTransport(collector))
    return Runtime(det, "http://collector:8004", 15.0, http=http), fake


def test_poll_cycle_posts_event_and_exposes_status(loaded):
    rt, fake = make_runtime(loaded, vector=flood_vector(loaded))
    with TestClient(create_app(rt, start_loop=False)) as client:
        assert client.get("/health").json() == {"status": "ok"}
        assert client.get("/ready").status_code == 503  # collector pas encore relevé
        asyncio.run(rt.poll_once())
        assert client.get("/ready").status_code == 200
        st = client.get("/api/v1/status").json()
        assert st["last_is_anomaly"] and st["last_trigger"] == "model" and st["last_event_id"]
        assert len(fake.requests) == 1
        metrics = client.get("/metrics").text
        assert 'resilience_anomaly_score{service="payment-api"}' in metrics


def test_collector_without_data_means_no_scoring_and_not_ready(loaded):
    rt, fake = make_runtime(loaded, features_status=503)
    with TestClient(create_app(rt, start_loop=False)) as client:
        asyncio.run(rt.poll_once())
        assert client.get("/ready").status_code == 503
        assert fake.requests == [] and rt.detector.last_decision is None


def test_not_ready_without_model():
    rt = Runtime(None, "http://collector:8004", 15.0, load_error="introuvable")
    with TestClient(create_app(rt, start_loop=False)) as client:
        assert client.get("/health").status_code == 200
        r = client.get("/ready")
        assert r.status_code == 503 and "modèle" in r.json()["problems"][0]
