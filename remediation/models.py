"""Modèles d'entrée/sortie du moteur.

`IncomingEvent` = AnomalyEvent du contrat (docs/contracts.md §3) + UN champ optionnel
additif `source_ip`, nécessaire aux actions `source: "from_event"` (blocage WAF).
Le contrat §3 ne porte pas l'IP source : c'est une extension rétro-compatible
(à émettre par le detector / Alertmanager), voir CAHIER-DES-CHARGES.md.
"""

from __future__ import annotations

import ipaddress
from datetime import UTC, datetime
from typing import Any

from pydantic import ConfigDict, field_validator
from resilience_common import AnomalyEvent


class IncomingEvent(AnomalyEvent):
    model_config = ConfigDict(extra="ignore")

    source_ip: str | None = None

    @field_validator("source_ip")
    @classmethod
    def _valid_ip(cls, v: str | None) -> str | None:
        if v is None:
            return None
        # Une seule adresse IP littérale : jamais de réseau, de nom ni de texte libre
        # (la valeur finit dans une conf Nginx -> pas d'injection possible).
        return str(ipaddress.ip_address(v.strip()))

    @property
    def detected_at(self) -> datetime:
        ts = self.ts
        return ts if ts.tzinfo else ts.replace(tzinfo=UTC)


def iso(dt: datetime) -> str:
    """ISO 8601 UTC avec millisecondes (format du contrat)."""
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def utcnow() -> datetime:
    return datetime.now(UTC)


def parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def jsonable(data: dict[str, Any] | None) -> dict[str, Any]:
    return dict(data or {})
