"""Adaptateur Alertmanager → `AnomalyEvent` (contrat §3) — chemin SOC, secondaire (ticket #13).

Le détecteur ML reste le chemin PRINCIPAL de déclenchement (`POST /events`). Les règles SOC
(Prometheus `infra/prometheus/rules/soc.yml`, miroir des règles Grafana) passent par Alertmanager,
qui poste son webhook (`{"alerts": [...]}`) sur `POST /events/alertmanager`, authentifié par le même
Bearer interne. Chaque alerte **firing** portant un label `incident_type` de l'énumération figée est
traduite en `IncomingEvent` et soumise au moteur comme n'importe quel événement : mêmes garde-fous
(idempotence, incident actif, cooldown, table de décision).

Règles de traduction (documentées dans README-SOC.md) :
  - `status != firing`            → ignorée (les résolutions ne déclenchent rien) ;
  - label `incident_type` absent ou hors énumération → ignorée (jamais mappé sur `unknown` par défaut :
    une règle SOC qui ne dit pas quel incident elle détecte ne déclenche pas de remédiation) ;
  - `service` = label `service`, sinon service par défaut de l'incident_type ;
  - `event_id` = uuid5(fingerprint, startsAt) : la ré-émission périodique d'une même alerte
    (`repeat_interval`) est rejouée de façon idempotente par le moteur (`decision: replayed`) ;
  - `anomaly_score` / `threshold` = 1.0 (alerte seuil = binaire), sauf labels/annotations explicites ;
  - `source_ip` (label optionnel) validé par `IncomingEvent` (une seule adresse IP littérale) ;
  - `evidence.prometheus_query` = annotation `expr`, `features_top` = annotations `feature`/`value`.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from models import IncomingEvent
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from resilience_common import IncidentType

SOURCE = "alertmanager"
_NS = uuid.UUID("5f1c7f3e-6f4e-4a9b-9b7a-2e3f1a9c0d13")  # espace de noms des event_id SOC (figé)

# Service visé par défaut pour chaque incident_type quand l'alerte ne porte pas de label `service`.
DEFAULT_SERVICE: dict[IncidentType, str] = {
    IncidentType.SERVICE_FLOOD: "payment-api",
    IncidentType.AUTH_ABUSE: "auth",
    IncidentType.WEB_ATTACK: "waf",
    IncidentType.DATA_CORRUPTION: "payment-api",
    IncidentType.UNKNOWN: "payment-api",
}


class Alert(BaseModel):
    """Une alerte du webhook Alertmanager (format v4)."""

    model_config = ConfigDict(extra="ignore")

    status: Literal["firing", "resolved"]
    labels: dict[str, str] = Field(default_factory=dict)
    annotations: dict[str, str] = Field(default_factory=dict)
    startsAt: datetime | None = None  # noqa: N815 — nom imposé par Alertmanager
    fingerprint: str | None = None

    @property
    def name(self) -> str:
        return self.labels.get("alertname", "?")


class AlertmanagerPayload(BaseModel):
    """Corps du webhook Alertmanager : seul `alerts` nous intéresse (le reste est ignoré)."""

    model_config = ConfigDict(extra="ignore")

    version: str | None = None
    status: str | None = None
    receiver: str | None = None
    alerts: list[Alert] = Field(min_length=1)


class Skipped(BaseModel):
    alertname: str
    reason: str


def _float(*values: str | None, default: float) -> float:
    for v in values:
        if v is None:
            continue
        try:
            return float(v)
        except ValueError:
            continue
    return default


def _event_id(alert: Alert) -> str:
    if alert.fingerprint:
        starts = alert.startsAt.isoformat() if alert.startsAt else ""
        return str(uuid.uuid5(_NS, f"{alert.fingerprint}|{starts}"))
    return str(uuid.uuid4())


def to_event(alert: Alert, *, now: datetime | None = None) -> IncomingEvent | Skipped:
    """Traduit UNE alerte en `IncomingEvent`, ou explique pourquoi elle est ignorée."""
    if alert.status != "firing":
        return Skipped(alertname=alert.name, reason="alerte résolue : aucune remédiation déclenchée")
    raw_type = alert.labels.get("incident_type")
    if not raw_type:
        return Skipped(alertname=alert.name, reason="label incident_type absent")
    try:
        incident_type = IncidentType(raw_type)
    except ValueError:
        return Skipped(alertname=alert.name, reason=f"incident_type inconnu : {raw_type!r}")

    ts = alert.startsAt if alert.startsAt and alert.startsAt.year > 1 else (now or datetime.now(UTC))
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    labels, ann = alert.labels, alert.annotations
    payload: dict[str, Any] = {
        "event_id": _event_id(alert),
        "ts": ts.isoformat(),
        "source": SOURCE,
        "service": labels.get("service") or DEFAULT_SERVICE[incident_type],
        "anomaly_score": _float(labels.get("anomaly_score"), ann.get("anomaly_score"), default=1.0),
        "threshold": _float(labels.get("threshold"), ann.get("threshold"), default=1.0),
        "incident_type": incident_type.value,
        "features_top": [],
        "evidence": {"prometheus_query": ann.get("expr") or ann.get("query") or None},
        "source_ip": labels.get("source_ip") or None,
    }
    if ann.get("value") is not None:
        payload["features_top"] = [{"name": ann.get("feature") or alert.name,
                                    "value": _float(ann.get("value"), default=0.0), "z": 0.0}]
    try:
        return IncomingEvent.model_validate(payload)
    except ValidationError as exc:  # ex. source_ip non littérale : on ignore l'alerte, jamais 500
        first = exc.errors()[0]
        return Skipped(alertname=alert.name, reason=f"{'.'.join(str(p) for p in first['loc'])}: {first['msg']}")


def to_events(payload: AlertmanagerPayload, *, now: datetime | None = None
              ) -> tuple[list[tuple[Alert, IncomingEvent]], list[Skipped]]:
    """Traduit tout le webhook : (alertes acceptées avec leur événement, alertes ignorées)."""
    accepted: list[tuple[Alert, IncomingEvent]] = []
    skipped: list[Skipped] = []
    for alert in payload.alerts:
        out = to_event(alert, now=now)
        if isinstance(out, Skipped):
            skipped.append(out)
        else:
            accepted.append((alert, out))
    return accepted, skipped
