"""Diffusion de la timeline d'incident au dashboard (Server-Sent Events).

Chaque événement de timeline est d'abord PERSISTÉ (journal.timeline, id croissant), puis
diffusé aux abonnés. L'id SQLite sert d'`id:` SSE : un client qui se reconnecte envoie
`Last-Event-ID` et rejoue ce qu'il a manqué, sans trou ni doublon.

Phases : detection -> decision -> action -> verification -> closure | escalation
Statuts : info | running | ok | ko | failed | skipped | dry_run
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncIterator

from journal import Journal


class Broker:
    def __init__(self) -> None:
        self._subs: set[asyncio.Queue[dict[str, Any]]] = set()

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=1000)
        self._subs.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[dict[str, Any]]) -> None:
        self._subs.discard(q)

    def publish(self, record: dict[str, Any]) -> None:
        for q in list(self._subs):
            try:
                q.put_nowait(record)
            except asyncio.QueueFull:  # consommateur trop lent : on le coupe, il se reconnectera
                self._subs.discard(q)

    @property
    def subscribers(self) -> int:
        return len(self._subs)


def frame(record: dict[str, Any]) -> str:
    """Trame SSE : `id` = id de timeline, `event: timeline`, `data` = JSON sur une ligne."""
    return f"id: {record['id']}\nevent: timeline\ndata: {json.dumps(record, ensure_ascii=False)}\n\n"


async def sse_stream(
    journal: Journal,
    broker: Broker,
    *,
    since: int | None,
    incident_id: str | None = None,
    follow: bool = True,
    keepalive_s: float = 15.0,
    backlog: int = 50,
) -> AsyncIterator[str]:
    """Génère les trames SSE : rejeu depuis `since` puis flux temps réel."""
    queue = broker.subscribe() if follow else None  # abonné AVANT le rejeu : aucun trou
    try:
        if since is None:  # première connexion : les derniers événements pour reconstruire l'état
            since = max(0, journal.latest_timeline_id() - backlog)
        last = since
        yield "retry: 3000\n\n"
        for rec in journal.timeline_since(since, incident_id, limit=1000):
            last = rec["id"]
            yield frame(rec)
        if queue is None:
            return
        while True:
            try:
                rec = await asyncio.wait_for(queue.get(), timeout=keepalive_s)
            except asyncio.TimeoutError:
                yield ": keepalive\n\n"
                continue
            if rec["id"] <= last or (incident_id and rec["incident_id"] != incident_id):
                continue
            last = rec["id"]
            yield frame(rec)
    finally:
        if queue is not None:
            broker.unsubscribe(queue)
