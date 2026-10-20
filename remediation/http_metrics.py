"""Métriques HTTP du contrat (docs/contracts.md §2) : compteurs de `resilience_common.metrics`.

Les compteurs sont ceux de `resilience_common.metrics` (une seule déclaration dans le
registre Prometheus : les redéclarer ici provoquait `DuplicateTimeseries` au boot, puisque
`resilience_common` les enregistre déjà au niveau module). Le moteur conserve son propre
middleware (request_id + journalisation) et n'appelle que `observe()`.
"""

from __future__ import annotations

from resilience_common.metrics import http_request_duration_seconds, http_requests_total

__all__ = ["http_request_duration_seconds", "http_requests_total", "observe"]


def observe(service: str, method: str, route_path: str | None, status: int, seconds: float) -> None:
    path = route_path or "unmatched"  # gabarit de route : cardinalité bornée (jamais l'URL brute)
    http_requests_total.labels(service, method, path, str(status)).inc()
    http_request_duration_seconds.labels(service, method, path).observe(seconds)
