"""Métriques HTTP standard du contrat (docs/contracts.md §2), noms et labels exacts.

Les compteurs sont ceux de `resilience_common.metrics` (registre Prometheus global : les
redéclarer ici lève `DuplicateTimeseries` à l'import). `instrument()` de la lib n'est pas
utilisé car le middleware `request_context` de main.py mesure déjà chaque requête et
expose son propre /metrics ; il ne reste ici que l'enregistrement.
"""

from __future__ import annotations

from resilience_common.metrics import http_request_duration_seconds, http_requests_total


def observe(service: str, method: str, route_path: str | None, status: int, seconds: float) -> None:
    path = route_path or "unmatched"  # gabarit de route : cardinalité bornée (jamais l'URL brute)
    http_requests_total.labels(service, method, path, str(status)).inc()
    http_request_duration_seconds.labels(service, method, path).observe(seconds)
