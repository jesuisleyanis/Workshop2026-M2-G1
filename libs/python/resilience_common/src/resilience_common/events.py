"""Schéma d'événement d'anomalie conforme à docs/contracts.md §3.

Le détecteur ML émet un AnomalyEvent vers le moteur de remédiation
(POST /events, authentifié). Alertmanager peut émettre au même format.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4

from pydantic import BaseModel, Field

SCHEMA_VERSION = "1.0"

#: Noms d'événements (`event`) réservés par le contrat `docs/contracts.md §1`. Ces noms
#: alimentent les règles d'alerte SOC et les features ML : n'en émettre aucun autre sans mettre
#: à jour le contrat ET cet ensemble (test de conformité dans chaque composant qui émet des logs).
RESERVED_EVENTS: frozenset[str] = frozenset(
    {
        # auth
        "auth_login_success",
        "auth_login_failed",
        "auth_rate_limited",
        # payment-api
        "transaction_created",
        "transaction_rejected",
        "db_error",
        # waf
        "waf_blocked",
        # detector
        "anomaly_detected",
        "model_version_drift",
        # remediation
        "remediation_started",
        "remediation_action",
        "remediation_verified",
        "remediation_failed",
        "remediation_manual_action",
        # assistant
        "assistant_index_built",
        "assistant_index_empty",
        "assistant_store_error",
        "assistant_question_answered",
        "assistant_incident_summarized",
        "assistant_postmortem_generated",
        "assistant_action_proposed",
        "assistant_llm_unavailable",
        "assistant_http_request",
    }
)


class IncidentType(str, Enum):
    """Énumération figée faisant le pont détection -> table de décision (contrat §3).

    La distinction imposée par le sujet (§2, §3.4) entre restauration de
    DISPONIBILITÉ (service_flood) et correction de COMPROMISSION/CORRUPTION
    (data_corruption) est portée par ces valeurs : ne jamais mapper l'une sur l'autre.
    """

    SERVICE_FLOOD = "service_flood"
    AUTH_ABUSE = "auth_abuse"
    WEB_ATTACK = "web_attack"
    DATA_CORRUPTION = "data_corruption"
    UNKNOWN = "unknown"


class FeatureTop(BaseModel):
    """Feature dominante ayant contribué au score d'anomalie."""

    name: str
    value: float
    z: float = Field(description="Écart à la baseline en nombre d'écarts-types.")


class Evidence(BaseModel):
    """Requêtes de preuve pour l'investigation (traçabilité SOC)."""

    prometheus_query: str | None = None
    loki_query: str | None = None


class AnomalyEvent(BaseModel):
    """Événement d'anomalie — contrat d'intégration detector -> remediation."""

    schema_version: str = SCHEMA_VERSION
    event_id: str = Field(default_factory=lambda: str(uuid4()))
    ts: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    source: str = "detector"
    service: str
    anomaly_score: float
    threshold: float
    incident_type: IncidentType
    features_top: list[FeatureTop] = Field(default_factory=list)
    evidence: Evidence | None = None
