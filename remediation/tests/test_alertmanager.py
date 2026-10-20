"""Chemin SOC → remédiation (ticket #13) : adaptateur Alertmanager → AnomalyEvent et route /events/alertmanager.

- traduction : firing + incident_type → IncomingEvent conforme §3 ; résolues / sans incident_type ignorées ;
- idempotence : la ré-émission périodique d'une même alerte (fingerprint + startsAt) est rejouée ;
- route : authentifiée (401 sans Bearer), 202 avec accepted/skipped, 422 si le corps n'est pas un webhook.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from alertmanager import DEFAULT_SERVICE, AlertmanagerPayload, Skipped, to_event, to_events
from conftest import TOKEN, Env, make_settings, make_table
from fastapi.testclient import TestClient
from main import create_app
from resilience_common import IncidentType

AUTH = {"Authorization": f"Bearer {TOKEN}"}
STARTS = "2026-10-21T09:14:35.000Z"


def alert(incident_type: str | None = "service_flood", *, status: str = "firing", fingerprint: str = "abc123",
          labels: dict | None = None, annotations: dict | None = None, starts_at: str = STARTS) -> dict:
    lab = {"alertname": "SocServiceFlood", "severity": "critical"}
    if incident_type is not None:
        lab["incident_type"] = incident_type
    lab.update(labels or {})
    return {"status": status, "labels": lab, "annotations": annotations or {}, "startsAt": starts_at,
            "endsAt": "0001-01-01T00:00:00Z", "generatorURL": "http://prometheus:9090/graph", "fingerprint": fingerprint}


def webhook(*alerts: dict) -> dict:
    """Enveloppe v4 d'Alertmanager."""
    return {"receiver": "remediation", "status": "firing", "alerts": list(alerts),
            "groupLabels": {"incident_type": "service_flood"}, "commonLabels": {}, "commonAnnotations": {},
            "externalURL": "http://alertmanager:9093", "version": "4", "groupKey": "{}:{incident_type=\"service_flood\"}",
            "truncatedAlerts": 0}


# ------------------------------------------------------------------ adaptateur
def test_firing_alert_becomes_contract_event():
    payload = AlertmanagerPayload.model_validate(webhook(alert(
        labels={"service": "payment-api", "source_ip": "203.0.113.7"},
        annotations={"expr": "sum(rate(resilience_http_requests_total{status=~\"5..\"}[1m]))", "value": "3.2",
                     "feature": "ratio_5xx"})))
    accepted, skipped = to_events(payload)
    assert skipped == [] and len(accepted) == 1
    _, ev = accepted[0]
    assert ev.incident_type is IncidentType.SERVICE_FLOOD and ev.service == "payment-api"
    assert ev.source == "alertmanager" and ev.schema_version == "1.0"
    assert ev.anomaly_score == 1.0 and ev.threshold == 1.0  # alerte seuil = binaire
    assert ev.source_ip == "203.0.113.7"
    assert ev.ts == datetime(2026, 10, 21, 9, 14, 35, tzinfo=UTC)
    assert ev.evidence.prometheus_query.startswith("sum(rate(")
    assert [(f.name, f.value) for f in ev.features_top] == [("ratio_5xx", 3.2)]
    # Le JSON produit est un AnomalyEvent §3 valide (consommable tel quel par /events).
    body = json.loads(ev.model_dump_json())
    for field in ("schema_version", "event_id", "ts", "source", "service", "anomaly_score", "threshold", "incident_type"):
        assert field in body


@pytest.mark.parametrize("incident_type", [t.value for t in IncidentType])
def test_every_incident_type_has_a_default_service(incident_type):
    out = to_event(AlertmanagerPayload.model_validate(webhook(alert(incident_type))).alerts[0])
    assert out.service == DEFAULT_SERVICE[IncidentType(incident_type)]


def test_resolved_or_unlabelled_or_unknown_alerts_are_skipped_not_mapped_to_unknown():
    payload = AlertmanagerPayload.model_validate(webhook(
        alert(status="resolved"), alert(None), alert("ransomware"), alert("data_corruption")))
    accepted, skipped = to_events(payload)
    assert [ev.incident_type for _, ev in accepted] == [IncidentType.DATA_CORRUPTION]
    assert [s.reason.split(" ")[0] for s in skipped] == ["alerte", "label", "incident_type"]
    assert all(isinstance(s, Skipped) for s in skipped)


def test_invalid_source_ip_skips_the_alert_instead_of_failing():
    out = to_event(AlertmanagerPayload.model_validate(webhook(alert(labels={"source_ip": "1.2.3.4; deny all"}))).alerts[0])
    assert isinstance(out, Skipped) and "source_ip" in out.reason


def test_event_id_is_stable_for_the_same_alert_occurrence_and_differs_otherwise():
    a = to_event(AlertmanagerPayload.model_validate(webhook(alert())).alerts[0])
    b = to_event(AlertmanagerPayload.model_validate(webhook(alert())).alerts[0])
    c = to_event(AlertmanagerPayload.model_validate(webhook(alert(starts_at="2026-10-21T10:00:00Z"))).alerts[0])
    d = to_event(AlertmanagerPayload.model_validate(webhook(alert(fingerprint="other"))).alerts[0])
    assert a.event_id == b.event_id and len({a.event_id, c.event_id, d.event_id}) == 3


def test_zero_starts_at_falls_back_to_now():
    now = datetime(2026, 10, 21, 12, 0, tzinfo=UTC)
    out = to_event(AlertmanagerPayload.model_validate(webhook(alert(starts_at="0001-01-01T00:00:00Z"))).alerts[0], now=now)
    assert out.ts == now


# ------------------------------------------------------------------ route
@pytest.fixture
def client():
    env = Env(table=make_table(cooldown=0), verify=[True])
    app = create_app(make_settings(), table=env.engine.table, services=env.services)
    with TestClient(app) as c:
        c.env = env
        yield c


def test_webhook_requires_the_internal_bearer(client):
    r = client.post("/events/alertmanager", json=webhook(alert()))
    assert r.status_code == 401 and r.json()["error"]["code"] == "unauthorized"
    assert client.app.state.journal.list_incidents() == []


def test_webhook_triggers_remediation_and_repeats_are_idempotent(client):
    r = client.post("/events/alertmanager", json=webhook(alert("data_corruption", fingerprint="f1")), headers=AUTH)
    assert r.status_code == 202
    data = r.json()
    assert data["skipped"] == [] and data["accepted"][0]["decision"] == "started"
    incident_id = data["accepted"][0]["incident_id"]
    assert data["accepted"][0]["alertname"] == "SocServiceFlood"

    inc = client.get(f"/incidents/{incident_id}", headers=AUTH).json()
    assert inc["incident_type"] == "data_corruption"
    assert inc["timeline"][0]["data"]["source"] == "alertmanager"  # tracé dans la timeline (étape detection)

    # Alertmanager ré-émet la même alerte toutes les repeat_interval : même event_id -> rejouée, pas de 2e incident.
    again = client.post("/events/alertmanager", json=webhook(alert("data_corruption", fingerprint="f1")), headers=AUTH).json()
    assert again["accepted"][0]["decision"] in {"replayed", "duplicate"}
    assert again["accepted"][0]["incident_id"] == incident_id
    assert len(client.get("/incidents", headers=AUTH).json()["incidents"]) == 1


def test_webhook_reports_skipped_alerts_and_rejects_non_webhook_bodies(client):
    r = client.post("/events/alertmanager", json=webhook(alert(status="resolved"), alert(None)), headers=AUTH)
    assert r.status_code == 202 and r.json()["accepted"] == [] and len(r.json()["skipped"]) == 2
    assert client.app.state.journal.list_incidents() == []

    bad = client.post("/events/alertmanager", json={"service": "payment-api"}, headers=AUTH)  # un AnomalyEvent, pas un webhook
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "invalid_request"
    assert client.post("/events/alertmanager", json=webhook(), headers=AUTH).status_code == 422  # alerts vide


def test_non_finite_numbers_from_templates_fall_back_to_defaults():
    out = to_event(AlertmanagerPayload.model_validate(webhook(alert(
        labels={"anomaly_score": "inf"}, annotations={"value": "NaN", "threshold": "nan"}))).alerts[0])
    assert out.anomaly_score == 1.0 and out.threshold == 1.0 and out.features_top[0].value == 0.0
