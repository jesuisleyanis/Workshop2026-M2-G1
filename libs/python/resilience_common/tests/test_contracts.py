"""Tests des contrats transverses (docs/contracts.md). Source de vérité partagée."""

import json
import logging

from resilience_common.events import AnomalyEvent, FeatureTop, IncidentType
from resilience_common.logging import JsonFormatter, get_logger


def test_logger_emits_single_line_json_with_mandatory_fields(capsys):
    log = get_logger("payment-api")
    log.info(
        "Transaction accepted",
        extra={"event": "transaction_created", "request_id": "rid-1", "http_status": 200},
    )
    out = capsys.readouterr().out.strip()
    assert "\n" not in out  # une seule ligne
    payload = json.loads(out)
    for field in ("ts", "level", "service", "event", "message", "request_id"):
        assert field in payload
    assert payload["service"] == "payment-api"
    assert payload["event"] == "transaction_created"
    assert payload["http_status"] == 200


def test_logger_omits_absent_context_fields():
    record = logging.LogRecord("auth", logging.WARNING, "x", 1, "msg", None, None)
    record.event = "auth_login_failed"
    line = JsonFormatter("auth").format(record)
    payload = json.loads(line)
    assert payload["request_id"] is None  # toujours présent, null si absent
    assert "user" not in payload  # champ contextuel absent -> omis


def test_anomaly_event_matches_schema():
    event = AnomalyEvent(
        service="payment-api",
        anomaly_score=0.87,
        threshold=0.60,
        incident_type=IncidentType.SERVICE_FLOOD,
        features_top=[FeatureTop(name="req_per_s", value=420.0, z=9.2)],
    )
    dumped = event.model_dump(mode="json")
    assert dumped["schema_version"] == "1.0"
    assert dumped["incident_type"] == "service_flood"
    assert dumped["event_id"]  # généré
    assert dumped["features_top"][0]["name"] == "req_per_s"


def test_incident_types_are_frozen():
    # Garde-fou : l'énumération est le pont vers la table de décision.
    assert {t.value for t in IncidentType} == {
        "service_flood",
        "auth_abuse",
        "web_attack",
        "data_corruption",
        "unknown",
    }
