"""API du moteur de remédiation (FastAPI, port interne 8005, réseau `app` UNIQUEMENT).

Authentification (deux jetons distincts, comparaison à temps constant, fail closed) :
- jeton de SERVICE `REMEDIATION_TOKEN` : POST /events, POST /events/alertmanager et toutes les lectures
  (GET /incidents*, /stream, /decision-table, /waf/blocked-ips) — detector, Alertmanager, nginx du dashboard ;
- jeton OPÉRATEUR `REMEDIATION_OPERATOR_TOKEN` : écritures déclenchées par un humain
  (DELETE /waf/blocked-ips/{ip}). Le jeton de service y est refusé (403) : le nginx du dashboard, qui
  l'injecte pour les lectures, ne peut rien écrire à la place de l'opérateur.
Sondes (/health, /ready, /metrics) sans jeton — joignables seulement depuis les réseaux internes.
Le service n'est jamais publié (`ports:`) ni rattaché au réseau `edge`.
"""

from __future__ import annotations

import hmac
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any, Literal

import http_metrics
import httpx
from actions import ActionError, ActionParamError
from actions.docker_proxy import DockerProxy, DockerProxyError
from actions.runner import AnsibleRunnerAdapter
from alertmanager import AlertmanagerPayload, to_events
from blocklist import list_blocked_ips, remove_ip
from config import Settings
from decision import DecisionTable, DecisionTableError, load_decision_table
from engine import RemediationEngine, Services
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response, StreamingResponse
from journal import Journal
from models import IncomingEvent
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel, ConfigDict, Field
from resilience_common import get_logger
from timeline import Broker, sse_stream
from verify import ScriptVerifier

SERVICE = "remediation"
PROBES = frozenset({"/health", "/ready", "/metrics"})


class ManualAction(BaseModel):
    """Corps de POST /manual-actions : liste blanche stricte (cf. engine.MANUAL_ACTIONS)."""

    model_config = ConfigDict(extra="forbid")
    action: Literal["waf_block_ip", "restart_service"]
    params: dict[str, Any]
    reason: str | None = Field(default=None, max_length=200)


def _error(status: int, code: str, message: str, request: Request) -> JSONResponse:
    """Corps d'erreur du contrat : {"error": {"code", "message", "request_id"}}."""
    rid = getattr(request.state, "request_id", None)
    return JSONResponse(status_code=status, headers={"X-Request-ID": rid or ""},
                        content={"error": {"code": code, "message": message, "request_id": rid}})


def create_app(
    settings: Settings | None = None,
    *,
    table: DecisionTable | None = None,
    services: Services | None = None,
    http_transport: httpx.AsyncBaseTransport | None = None,
) -> FastAPI:
    settings = settings or Settings.from_env()
    log = get_logger(SERVICE)
    table = table or load_decision_table(settings.decision_table_path)  # invalide -> le service ne démarre pas

    journal = Journal(settings.db_path)
    broker = Broker()
    http = httpx.AsyncClient(transport=http_transport, follow_redirects=False)
    if services is None:
        services = Services(
            http=http,
            docker=DockerProxy(http, settings.docker_proxy_url, settings.docker_allow_recreate),
            runner=AnsibleRunnerAdapter(settings.ansible_private_data_dir, settings.ansible_project_dir),
            verifier=ScriptVerifier(settings.verify_tx_path, settings.verify_timeout_s),
        )
    engine = RemediationEngine(table=table, settings=settings, journal=journal, broker=broker,
                               services=services, log=log)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        orphans = journal.recover_orphans()
        if orphans:
            log.warning(f"{orphans} incident(s) interrompu(s) par un redémarrage",
                        extra={"event": "remediation_failed"})
        if not settings.token_configured:
            log.error("REMEDIATION_TOKEN absent ou trop court : /events refusera tout (fail closed)")
        if not settings.operator_token_configured:
            log.warning("REMEDIATION_OPERATOR_TOKEN absent, trop court ou égal au jeton de service : "
                        "actions opérateur refusées (fail closed)")
        yield
        await engine.shutdown()
        await http.aclose()
        journal.close()

    app = FastAPI(title="RESILIENCE-ALPHA remediation", version="1.0.0", lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url=None)  # pas de schéma exposé inutilement
    app.state.engine = engine
    app.state.journal = journal
    app.state.broker = broker
    app.state.settings = settings

    # --------------------------------------------------------------- middleware
    @app.middleware("http")
    async def request_context(request: Request, call_next):
        # On n'accepte un X-Request-ID entrant que s'il s'agit d'un UUID (anti log-forging,
        # parité avec auth/payment-api) ; toute autre valeur est remplacée.
        raw_rid = request.headers.get("x-request-id")
        try:
            rid = str(uuid.UUID(raw_rid)) if raw_rid else str(uuid.uuid4())
        except (ValueError, AttributeError, TypeError):
            rid = str(uuid.uuid4())
        request.state.request_id = rid
        t0 = time.monotonic()
        response = await call_next(request)
        response.headers["X-Request-ID"] = rid
        if request.url.path not in PROBES:
            route = request.scope.get("route")
            http_metrics.observe(SERVICE, request.method, getattr(route, "path", None),
                                 response.status_code, time.monotonic() - t0)
        if request.url.path not in PROBES and request.url.path != "/stream":
            log.info(f"{request.method} {request.url.path} -> {response.status_code}", extra={
                "request_id": rid, "client_ip": request.client.host if request.client else None,
                "http_method": request.method, "http_path": request.url.path,
                "http_status": response.status_code, "duration_ms": int((time.monotonic() - t0) * 1000)})
        return response

    @app.exception_handler(HTTPException)
    async def _http_exc(request: Request, exc: HTTPException):
        resp = _error(exc.status_code, _code(exc), str(exc.detail), request)
        if exc.headers:
            resp.headers.update(exc.headers)
        return resp

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError):
        return _error(422, "invalid_request", "; ".join(
            f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()[:5]), request)

    # --------------------------------------------------------------- authentification
    def _bearer(authorization: str | None) -> str | None:
        scheme, _, presented = (authorization or "").partition(" ")
        return presented.strip() if scheme.lower() == "bearer" else None

    def _matches(presented: str | None, expected: str | None) -> bool:
        return presented is not None and hmac.compare_digest(presented.encode(), (expected or "").encode())

    def _denied(request: Request, status: int, message: str) -> HTTPException:
        log.warning(message, extra={
            "request_id": getattr(request.state, "request_id", None),
            "client_ip": request.client.host if request.client else None,
            "http_method": request.method, "http_path": request.url.path, "http_status": status})
        if status == 401:
            return HTTPException(401, "unauthorized", headers={"WWW-Authenticate": "Bearer"})
        return HTTPException(status, "operator_token_required")

    def require_token(request: Request, authorization: str | None = Header(default=None)) -> None:
        """Jeton de SERVICE (SOPS). Comparaison à temps constant ; fail closed."""
        if not settings.token_configured:
            raise HTTPException(503, "auth_not_configured")
        if not _matches(_bearer(authorization), settings.token):
            raise _denied(request, 401, "Accès refusé : token absent ou invalide")

    def require_operator(request: Request, authorization: str | None = Header(default=None)) -> None:
        """Jeton OPÉRATEUR (humain). Le jeton de service est explicitement refusé (403) ; fail closed."""
        if not settings.operator_token_configured:
            raise HTTPException(503, "auth_not_configured")
        presented = _bearer(authorization)
        if _matches(presented, settings.operator_token):
            return
        if settings.token_configured and _matches(presented, settings.token):
            raise _denied(request, 403, "Action opérateur refusée : jeton de service présenté")
        raise _denied(request, 401, "Action opérateur refusée : jeton opérateur absent ou invalide")

    auth = Depends(require_token)
    operator = Depends(require_operator)

    # --------------------------------------------------------------- sondes
    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/ready")
    async def ready() -> JSONResponse:
        checks = {
            "decision_table": True,  # chargée et validée au démarrage
            "journal": journal.ping(),
            "auth_configured": settings.token_configured,
            "docker_socket_proxy": await services.docker.ping(),
        }
        ok = all(checks.values())
        return JSONResponse(status_code=200 if ok else 503,
                            content={"status": "ready" if ok else "not_ready", "checks": checks})

    @app.get("/metrics")
    async def metrics() -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    # --------------------------------------------------------------- API métier
    @app.post("/events", status_code=202, dependencies=[auth])
    async def post_event(event: IncomingEvent) -> dict[str, Any]:
        """Reçoit un AnomalyEvent (detector / Alertmanager) ; la remédiation tourne en arrière-plan."""
        sub = await engine.handle_event(event)
        return {"incident_id": sub.incident_id, "decision": sub.decision,
                "dry_run": sub.dry_run, "detail": sub.detail}

    @app.post("/manual-actions", dependencies=[operator])
    async def post_manual_action(body: ManualAction, request: Request):
        """Action confirmée par un opérateur depuis le dashboard (jamais appelée par l'assistant)."""
        try:
            return await engine.run_manual(body.action, body.params, body.reason)
        except (ActionParamError, ActionError) as exc:  # rien n'a été exécuté ni journalisé
            code = "invalid_params" if isinstance(exc, ActionParamError) else "action_refused"
            return _error(422, code, str(exc), request)

    @app.post("/events/alertmanager", status_code=202, dependencies=[auth])
    async def post_alertmanager(payload: AlertmanagerPayload) -> dict[str, Any]:
        """Webhook Alertmanager (chemin SOC, secondaire) : chaque alerte firing avec un label
        `incident_type` est traduite en AnomalyEvent (§3) puis soumise au moteur comme /events."""
        accepted, skipped = to_events(payload)
        results = []
        for alert, event in accepted:
            sub = await engine.handle_event(event)
            results.append({"alertname": alert.name, "incident_id": sub.incident_id, "decision": sub.decision,
                            "dry_run": sub.dry_run, "detail": sub.detail})
        for sk in skipped:
            log.info(f"Alerte SOC ignorée : {sk.alertname} ({sk.reason})")
        return {"accepted": results, "skipped": [sk.model_dump() for sk in skipped]}

    @app.get("/incidents", dependencies=[auth])
    async def list_incidents(limit: int = Query(50, ge=1, le=500)) -> dict[str, Any]:
        return {"incidents": journal.list_incidents(limit)}

    @app.get("/incidents/{incident_id}", dependencies=[auth])
    async def get_incident(incident_id: str, request: Request):
        inc = journal.get_incident(incident_id)
        if inc is None:
            return _error(404, "incident_not_found", "incident inconnu", request)
        return inc

    @app.get("/waf/blocked-ips", dependencies=[auth])
    async def blocked_ips() -> dict[str, Any]:
        """IP actuellement en liste noire du WAF (lecture seule), enrichies par le journal."""
        return {"blocked": list_blocked_ips(settings.waf_deny_file, journal.last_blocks())}

    @app.delete("/waf/blocked-ips/{ip}", dependencies=[operator])
    async def unblock_ip(ip: str, request: Request):
        """Déblocage par l'opérateur (bouton du dashboard) : retire l'IP de la deny-list, recharge le WAF.

        Hors boucle de reprise (aucun incident en dépend) : action d'administration, tracée dans les logs.
        Jeton OPÉRATEUR exigé : le jeton de service (détenu par le nginx du dashboard) est refusé.
        """
        try:
            removed = remove_ip(settings.waf_deny_file, ip)
        except ValueError:
            return _error(400, "invalid_ip", "adresse IP littérale attendue", request)
        if not removed:
            return _error(404, "ip_not_blocked", "cette IP n'est pas dans la liste noire du WAF", request)
        log.warning(f"IP {ip} débloquée par l'opérateur (dashboard)",
                    extra={"event": "remediation_action", "client_ip": ip})
        try:
            reloaded = await services.docker.find_containers(settings.waf_service)
            for cid in reloaded:
                await services.docker.reload(cid)  # SIGHUP = `nginx -s reload`, via le proxy
        except DockerProxyError:
            return _error(502, "waf_reload_failed",
                          "IP retirée de la liste noire mais WAF non rechargé (réessayer)", request)
        return {"unblocked": ip, "waf_reloaded": len(reloaded)}

    @app.get("/decision-table", dependencies=[auth])
    async def get_table() -> dict[str, Any]:
        return table.model_dump(mode="json")

    @app.get("/stream", dependencies=[auth])
    async def stream(
        incident_id: str | None = Query(None),
        since: int | None = Query(None, ge=0),
        follow: bool = Query(True),
        last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    ) -> StreamingResponse:
        """Timeline temps réel (SSE) : detection -> decision -> action -> verification -> closure."""
        if since is None and last_event_id and last_event_id.isdigit():
            since = int(last_event_id)
        gen = sse_stream(journal, broker, since=since, incident_id=incident_id, follow=follow,
                         keepalive_s=settings.sse_keepalive_s)
        return StreamingResponse(gen, media_type="text/event-stream", headers={
            "Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"})

    return app


_CODES = {400: "bad_request", 401: "unauthorized", 403: "operator_token_required", 404: "not_found",
          503: "auth_not_configured"}


def _code(exc: HTTPException) -> str:
    return _CODES.get(exc.status_code, "error")


def app_factory() -> FastAPI:  # uvicorn --factory main:app_factory
    try:
        return create_app()
    except DecisionTableError as exc:
        raise SystemExit(f"decision_table.yml invalide : {exc}") from exc
