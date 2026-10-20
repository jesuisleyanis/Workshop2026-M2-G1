"""Métriques Prometheus normalisées conforme à docs/contracts.md §2.

Préfixe commun `resilience_`. Les services importent ces objets plutôt que de
redéclarer des métriques, pour garantir des noms et labels identiques.
"""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

METRIC_PREFIX = "resilience_"

# --- Métier (exposées explicitement par les services) ---------------------------

transactions_total = Counter(
    "resilience_transactions_total",
    "Nombre de transactions traitées.",
    labelnames=("result",),  # created | rejected
)

auth_logins_total = Counter(
    "resilience_auth_logins_total",
    "Tentatives de connexion.",
    labelnames=("result",),  # success | failed
)

auth_rate_limited_total = Counter(
    "resilience_auth_rate_limited_total",
    "Requêtes rejetées par le rate-limit de l'authentification.",
)

db_errors_total = Counter(
    "resilience_db_errors_total",
    "Erreurs base de données rencontrées.",
)

waf_blocked_total = Counter(
    "resilience_waf_blocked_total",
    "Requêtes bloquées par le WAF (exporté depuis les logs Nginx/ModSec).",
    labelnames=("rule",),
)

# --- ML / remédiation -----------------------------------------------------------

anomaly_score = Gauge(
    "resilience_anomaly_score",
    "Score d'anomalie temps réel produit par le détecteur ML.",
    labelnames=("service",),
)

# --- Consigne additionnelle 1 : reconnaissance de visage + auth à étapes + LED ---

face_verifications_total = Counter(
    "resilience_face_verifications_total",
    "Vérifications faciales 1:1 (identifiant <-> visage).",
    labelnames=("result",),  # match | nomatch | error
)

face_verify_duration_seconds = Histogram(
    "resilience_face_verify_duration_seconds",
    "Latence d'une vérification faciale.",
)

face_enrollments = Gauge(
    "resilience_face_enrollments",
    "Nombre de visages enrôlés (embeddings stockés).",
)

auth_face_steps_total = Counter(
    "resilience_auth_face_steps_total",
    "Issues de l'étape visage de l'authentification back-office.",
    labelnames=("result",),  # recognized | rejected
)

auth_lockouts_total = Counter(
    "resilience_auth_lockouts_total",
    "Blocages d'accès au back-office (quota d'échecs atteint).",
)

led_publish_total = Counter(
    "resilience_led_publish_total",
    "Publications d'état LED vers le broker MQTT.",
    labelnames=("state", "result"),  # state sémantique ; result ok | error
)

# --- HTTP standard (contrat §2) -------------------------------------------------
# Noms et labels EXACTS du contrat. L'ordre des labels (service avant path) est
# significatif : il conditionne l'ordre d'affichage dans /metrics.
http_requests_total = Counter(
    "resilience_http_requests_total",
    "Requêtes HTTP traitées.",
    labelnames=("service", "method", "path", "status"),
)

http_request_duration_seconds = Histogram(
    "resilience_http_request_duration_seconds",
    "Latence serveur des requêtes HTTP.",
    labelnames=("service", "method", "path"),
)

remediation_actions_total = Counter(
    "resilience_remediation_actions_total",
    "Actions de remédiation exécutées.",
    labelnames=("action", "result"),
)

mttd_seconds = Gauge(
    "resilience_mttd_seconds",
    "Délai détection -> première action de remédiation (dit MTTD) du dernier incident.",
    labelnames=("incident_id",),
)

mttr_seconds = Gauge(
    "resilience_mttr_seconds",
    "Mean Time To Recover du dernier incident.",
    labelnames=("incident_id",),
)

# Note : les métriques HTTP standard (resilience_http_requests_total,
# resilience_http_request_duration_seconds) sont produites par
# prometheus-fastapi-instrumentator — voir instrument() ci-dessous.


_EXCLUDED_PATHS = frozenset({"/metrics", "/health", "/ready"})


def instrument(app, service: str) -> None:
    """Branche l'instrumentation HTTP et l'endpoint /metrics sur une app FastAPI.

    Produit EXACTEMENT les métriques du contrat §2 :
      - resilience_http_requests_total{service, method, path, status}
      - resilience_http_request_duration_seconds{service, method, path}

    Le label `path` est le gabarit de route (`/api/v1/accounts`), pas l'URL brute,
    pour borner la cardinalité ; les requêtes non routées sont étiquetées "unmatched".
    Importé par chaque service exposant du HTTP.
    """
    import time

    from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
    from starlette.requests import Request
    from starlette.responses import PlainTextResponse, Response

    @app.middleware("http")
    async def _metrics_middleware(request: Request, call_next):  # type: ignore[no-untyped-def]
        path_tmpl = request.scope.get("path", request.url.path)
        if path_tmpl in _EXCLUDED_PATHS:
            return await call_next(request)
        start = time.perf_counter()
        response = await call_next(request)
        # Gabarit de route si disponible (évite l'explosion de cardinalité sur les IDs).
        route = request.scope.get("route")
        path = getattr(route, "path", None) or ("unmatched" if response.status_code == 404 else path_tmpl)
        elapsed = time.perf_counter() - start
        http_requests_total.labels(service, request.method, path, str(response.status_code)).inc()
        http_request_duration_seconds.labels(service, request.method, path).observe(elapsed)
        return response

    @app.get("/metrics")
    def _metrics() -> Response:  # type: ignore[no-untyped-def]
        return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)
