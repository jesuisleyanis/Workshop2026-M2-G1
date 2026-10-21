"""Logging JSON structuré conforme à docs/contracts.md §1.

Tous les services émettent des logs JSON sur une seule ligne sur stdout.
Promtail les récupère via le driver de logs Docker et les pousse dans Loki.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any

# Événements normalisés réservés (docs/contracts.md §1). Tenus ici comme garde-fou
# documentaire ; un événement hors liste n'est pas rejeté mais doit être ajouté au contrat.
NORMALIZED_EVENTS = frozenset(
    {
        "auth_login_success",
        "auth_login_failed",
        "auth_rate_limited",
        "transaction_created",
        "transaction_rejected",
        "db_error",
        "beneficiary_added",
        "beneficiary_removed",
        "beneficiary_rejected",
        "transaction_access_denied",
        "card_frozen",
        "card_unfrozen",
        "card_settings_changed",
        "card_access_denied",
        "waf_blocked",
        "anomaly_detected",
        "remediation_started",
        "remediation_action",
        "remediation_verified",
        "remediation_failed",
    }
)

_CONTEXT_FIELDS = (
    "request_id",
    "user",
    "client_ip",
    "http_method",
    "http_path",
    "http_status",
    "duration_ms",
    "anomaly_score",
    "incident_id",
)


class JsonFormatter(logging.Formatter):
    """Formate chaque enregistrement en une ligne JSON conforme au contrat."""

    def __init__(self, service: str) -> None:
        super().__init__()
        self.service = service

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.")
            + f"{int(record.created % 1 * 1000):03d}Z",
            "level": record.levelname,
            "service": self.service,
            "event": getattr(record, "event", "log"),
            "message": record.getMessage(),
        }
        # request_id est toujours présent (null si absent) pour corréler.
        payload["request_id"] = getattr(record, "request_id", None)
        for field in _CONTEXT_FIELDS:
            if field == "request_id":
                continue
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def get_logger(service: str, level: int = logging.INFO) -> logging.Logger:
    """Renvoie un logger configuré pour émettre le format JSON du contrat.

    Usage :
        log = get_logger("payment-api")
        log.info("Transaction accepted", extra={"event": "transaction_created",
                 "request_id": rid, "user": "demo01", "http_status": 200})
    """
    logger = logging.getLogger(service)
    logger.setLevel(level)
    logger.propagate = False
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JsonFormatter(service))
        logger.addHandler(handler)
    return logger
