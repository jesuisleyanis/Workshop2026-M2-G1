"""Tests des contrats transverses (docs/contracts.md). Source de vérité partagée."""

import json
import logging

import pytest
from pydantic import ValidationError

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


def test_anomaly_event_source_ip_is_optional_and_a_single_ip_literal():
    base = dict(service="payment-api", anomaly_score=0.9, threshold=0.7, incident_type="service_flood")
    assert AnomalyEvent(**base).source_ip is None  # champ additif : rétro-compatible
    assert AnomalyEvent(**base, source_ip=" 192.168.137.42 ").source_ip == "192.168.137.42"
    for bad in ("10.0.0.0/8", "attacker.example", "1.2.3.4; deny all", ""):
        with pytest.raises(ValidationError):
            AnomalyEvent(**base, source_ip=bad)


def test_incident_types_are_frozen():
    # Garde-fou : l'énumération est le pont vers la table de décision.
    assert {t.value for t in IncidentType} == {
        "service_flood",
        "auth_abuse",
        "web_attack",
        "data_corruption",
        "unknown",
    }


def test_reserved_events_match_contract_table():
    """RESERVED_EVENTS = exactement les `event` réservés par docs/contracts.md §1.

    Garde-fou anti-dérive : tout événement ajouté/retiré dans le contrat doit l'être ici
    (et réciproquement), sinon les règles SOC et le test de conformité des composants mentent.
    """
    import re
    from pathlib import Path

    from resilience_common.events import RESERVED_EVENTS

    doc = (Path(__file__).resolve().parents[4] / "docs" / "contracts.md").read_text(
        encoding="utf-8"
    )
    section = doc.split("### Événements normalisés", 1)[1].split("### Exemple", 1)[0]
    # Lignes de tableau « | `event_name` | service | sens | » (on ignore l'en-tête/séparateur).
    documented = {
        m.group(1)
        for line in section.splitlines()
        if (m := re.match(r"\|\s*`([a-z_]+)`\s*\|", line))
    } - {"event"}  # en-tête du tableau « | `event` | Service | … | »
    assert documented, "aucun événement extrait du contrat (format du tableau modifié ?)"
    assert documented == set(RESERVED_EVENTS), (
        f"désaccord contrat/RESERVED_EVENTS : "
        f"contrat seul={documented - set(RESERVED_EVENTS)}, code seul={set(RESERVED_EVENTS) - documented}"
    )
