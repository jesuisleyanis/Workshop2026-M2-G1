"""L'assistant n'émet que des événements réservés par le contrat (docs/contracts.md §1).

Le §1 réserve les noms d'`event`. Ce test échoue si un log de l'assistant introduit un nom
hors contrat (il faut alors l'ajouter au contrat ET à resilience_common.RESERVED_EVENTS).
"""

from __future__ import annotations

import re
from pathlib import Path

from resilience_common.events import RESERVED_EVENTS

APP_DIR = Path(__file__).resolve().parents[1] / "app"


def _emitted_event_names() -> set[str]:
    names: set[str] = set()
    for src in APP_DIR.rglob("*.py"):
        text = src.read_text(encoding="utf-8")
        # Motifs de log du contrat : extra={"event": "xxx"} ou "event": "xxx".
        names |= set(re.findall(r'["\']event["\']\s*:\s*["\']([a-z_]+)["\']', text))
    return names


def test_assistant_emits_only_reserved_events():
    emitted = _emitted_event_names()
    assert emitted, "aucun événement détecté dans assistant/app (motif de recherche à revoir ?)"
    unknown = emitted - set(RESERVED_EVENTS)
    assert not unknown, f"événements hors contrat §1 : {sorted(unknown)} (déclarer dans docs/contracts.md)"
