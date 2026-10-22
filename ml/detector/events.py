"""Construction de l'AnomalyEvent (docs/contracts.md §3)."""

from __future__ import annotations

from datetime import UTC, datetime

from resilience_common import AnomalyEvent, FeatureTop, IncidentType
from resilience_common.events import Evidence

from ml.shared.features import top_features

# Requêtes de preuve par type d'incident, pour l'investigation (SOC / dashboard / assistant).
# Les noms de métriques / d'événements viennent de contracts.md §1 et §2.
EVIDENCE: dict[IncidentType, tuple[str, str]] = {
    IncidentType.SERVICE_FLOOD: (
        "rate(resilience_http_requests_total[1m])",
        '{service="payment-api"} |= "http_status"',
    ),
    IncidentType.AUTH_ABUSE: (
        'rate(resilience_auth_logins_total{result="failed"}[1m])',
        '{service="auth"} |= "auth_login_failed"',
    ),
    IncidentType.WEB_ATTACK: (
        "rate(resilience_waf_blocked_total[1m])",
        # label Loki = service Compose émetteur (posé par Promtail) : waf-exporter, pas waf
        '{service="waf-exporter"} |= "waf_blocked"',
    ),
    IncidentType.DATA_CORRUPTION: (
        "rate(resilience_db_errors_total[1m])",
        '{service="payment-api"} |= "db_error"',
    ),
    IncidentType.UNKNOWN: (
        "resilience_anomaly_score",
        '{service=~"payment-api|auth|waf"} |= "ERROR"',
    ),
}


def build_event(
    *,
    service: str,
    score: float,
    threshold: float,
    incident_type: IncidentType,
    vector: list[float],
    z: dict[str, float],
    now: datetime | None = None,
    source_ip: str | None = None,
) -> AnomalyEvent:
    """Assemble l'événement ; la validation pydantic garantit la conformité au schéma partagé."""
    prom_q, loki_q = EVIDENCE[incident_type]
    ts = (now or datetime.now(UTC)).astimezone(UTC)
    return AnomalyEvent(
        ts=ts.replace(microsecond=ts.microsecond // 1000 * 1000),  # précision ms (contrat)
        service=service,
        anomaly_score=round(score, 4),
        threshold=round(threshold, 4),
        incident_type=incident_type,
        features_top=[FeatureTop(**f) for f in top_features(vector, z)],
        evidence=Evidence(prometheus_query=prom_q, loki_query=loki_q),
        source_ip=source_ip,
    )
