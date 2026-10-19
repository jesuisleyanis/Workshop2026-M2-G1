"""Métriques HTTP standard du contrat (docs/contracts.md §2), noms et labels exacts.

`resilience_common.metrics.instrument()` n'est volontairement pas utilisé : à ce jour il
expose `resilience_http_http_requests_total{handler,...}` (préfixe doublé, label `handler`
au lieu de `service`/`path`), non conforme au contrat. À corriger dans la lib commune.
"""

from __future__ import annotations

from prometheus_client import Counter, Histogram

http_requests_total = Counter(
    "resilience_http_requests_total", "Requêtes HTTP traitées.",
    labelnames=("service", "method", "path", "status"),
)
http_request_duration_seconds = Histogram(
    "resilience_http_request_duration_seconds", "Latence serveur des requêtes HTTP.",
    labelnames=("service", "method", "path"),
)


def observe(service: str, method: str, route_path: str | None, status: int, seconds: float) -> None:
    path = route_path or "unmatched"  # gabarit de route : cardinalité bornée (jamais l'URL brute)
    http_requests_total.labels(service, method, path, str(status)).inc()
    http_request_duration_seconds.labels(service, method, path).observe(seconds)
