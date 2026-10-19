"""Librairie partagée RESILIENCE-ALPHA.

Source de vérité pour les contrats transverses (voir docs/contracts.md) :
logging JSON structuré, métriques Prometheus normalisées, schéma d'événement d'anomalie.
"""

from resilience_common.events import (
    RESERVED_EVENTS,
    SCHEMA_VERSION,
    AnomalyEvent,
    FeatureTop,
    IncidentType,
)
from resilience_common.logging import get_logger
from resilience_common.metrics import (
    METRIC_PREFIX,
    anomaly_score,
    auth_logins_total,
    auth_rate_limited_total,
    db_errors_total,
    transactions_total,
)

__all__ = [
    "AnomalyEvent",
    "RESERVED_EVENTS",
    "FeatureTop",
    "IncidentType",
    "SCHEMA_VERSION",
    "get_logger",
    "METRIC_PREFIX",
    "anomaly_score",
    "auth_logins_total",
    "auth_rate_limited_total",
    "db_errors_total",
    "transactions_total",
]
