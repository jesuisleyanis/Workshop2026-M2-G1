"""Métriques HTTP du contrat (docs/contracts.md §2) : compteurs de `resilience_common.metrics`.

`instrument()` n'est pas utilisé : il ajouterait une seconde route /metrics et un second
middleware, alors que `main.request_context` mesure déjà chaque requête (request-id, logs).
"""

from __future__ import annotations

from resilience_common.metrics import http_request_duration_seconds, http_requests_total


def observe(service: str, method: str, route_path: str | None, status: int, seconds: float) -> None:
    path = route_path or "unmatched"  # gabarit de route : cardinalité bornée (jamais l'URL brute)
    http_requests_total.labels(service, method, path, str(status)).inc()
    http_request_duration_seconds.labels(service, method, path).observe(seconds)
