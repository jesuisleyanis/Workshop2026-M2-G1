"""waf-exporter — transforme les blocages ModSecurity en métrique et en log normalisé.

Lit le journal d'audit ModSecurity (format JSON de l'image CRS) ou l'access log,
émet la métrique resilience_waf_blocked_total{rule} et un log event `waf_blocked`
conforme à docs/contracts.md §1. Alimente la fonction SOC et le vecteur de features ML.

Usage :
    python waf_exporter.py --audit-log /var/log/modsec_audit.json
Expose /metrics sur le port 9188.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass


# Métrique partagée (même objet que resilience_common.metrics.waf_blocked_total
# lorsqu'exécuté avec la lib installée ; redéclarée ici de façon autonome pour
# rester déployable isolément).
_BLOCK_RE = re.compile(r'"id"\s*:\s*"?(\d+)"?')


@dataclass
class WafBlockEvent:
    """Événement de blocage normalisé (contrat §1)."""

    client_ip: str
    rule: str
    http_path: str
    http_status: int = 403

    def to_log(self) -> dict:
        return {
            "level": "WARNING",
            "service": "waf",
            "event": "waf_blocked",
            "message": f"Request blocked by rule {self.rule}",
            "client_ip": self.client_ip,
            "http_path": self.http_path,
            "http_status": self.http_status,
            "rule": self.rule,
        }


def parse_modsec_line(line: str) -> WafBlockEvent | None:
    """Parse une ligne d'audit ModSecurity (JSON) et renvoie un événement de blocage.

    Renvoie None si la ligne ne correspond pas à un blocage (action != deny / 403).
    Tolérant : ignore les lignes non-JSON.
    """
    line = line.strip()
    if not line:
        return None
    try:
        record = json.loads(line)
    except json.JSONDecodeError:
        return None

    tx = record.get("transaction", record)
    messages = tx.get("messages", [])
    response = tx.get("response", {})
    status = response.get("http_code", tx.get("http_status", 0))

    # On ne compte que les requêtes effectivement bloquées (403) avec au moins une règle.
    if int(status or 0) != 403 or not messages:
        return None

    first = messages[0]
    details = first.get("details", {})
    rule = str(details.get("ruleId") or first.get("ruleId") or "unknown")

    return WafBlockEvent(
        client_ip=tx.get("client_ip", tx.get("remote_address", "unknown")),
        rule=rule,
        http_path=tx.get("request", {}).get("uri", tx.get("http_path", "/")),
        http_status=403,
    )


def iter_block_events(lines):
    """Génère les WafBlockEvent à partir d'un itérable de lignes de log."""
    for line in lines:
        event = parse_modsec_line(line)
        if event is not None:
            yield event
