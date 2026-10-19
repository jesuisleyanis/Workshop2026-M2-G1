"""Contexte de requête + logs conformes à docs/contracts.md §1 + format d'erreur REST.

Le contrat prévoit un middleware FastAPI qui injecte request_id / client_ip / http_*
dans les logs. resilience_common ne le fournit pas encore : il vit ici (copie du module
homonyme de auth) en attendant d'être remonté dans la lib partagée.
"""

from __future__ import annotations

import logging
import time
import uuid
from contextvars import ContextVar

from fastapi.responses import JSONResponse
from starlette.datastructures import Headers, MutableHeaders

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
client_ip_var: ContextVar[str | None] = ContextVar("client_ip", default=None)
http_method_var: ContextVar[str | None] = ContextVar("http_method", default=None)
http_path_var: ContextVar[str | None] = ContextVar("http_path", default=None)
started_var: ContextVar[float | None] = ContextVar("started", default=None)
user_var: ContextVar[str | None] = ContextVar("user", default=None)


def client_ip_from(headers: Headers, peer: str | None, hops: int) -> str | None:
    """IP cliente telle que vue derrière le WAF.

    On lit X-Forwarded-For en partant de la DROITE (entrée ajoutée par le proxy de
    confiance le plus proche) : la partie gauche est contrôlée par le client et ne doit
    jamais être crue. `hops` = nombre de proxys de confiance devant le service.
    """
    xff = headers.get("x-forwarded-for")
    if xff:
        parts = [p.strip() for p in xff.split(",") if p.strip()]
        if len(parts) >= hops >= 1:
            return parts[-hops]
    return peer


def _valid_uuid(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return str(uuid.UUID(value))
    except ValueError:
        return None


class RequestContextMiddleware:
    """Middleware ASGI pur : fixe le contexte de requête et renvoie X-Request-ID.

    Les ContextVar ne sont volontairement pas réinitialisées en sortie : chaque requête
    s'exécute dans sa propre tâche, et le handler des 500 (ServerErrorMiddleware, plus
    externe) doit encore voir le request_id.
    """

    def __init__(self, app, trusted_proxy_hops: int = 1) -> None:
        self.app = app
        self.hops = trusted_proxy_hops

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        # On n'accepte un X-Request-ID entrant que s'il s'agit d'un UUID (anti log-forging).
        rid = _valid_uuid(headers.get("x-request-id")) or str(uuid.uuid4())
        peer = scope["client"][0] if scope.get("client") else None
        request_id_var.set(rid)
        client_ip_var.set(client_ip_from(headers, peer, self.hops))
        http_method_var.set(scope["method"])
        http_path_var.set(scope["path"])
        started_var.set(time.perf_counter())
        user_var.set(None)

        async def send_with_id(message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message)["X-Request-ID"] = rid
            await send(message)

        await self.app(scope, receive, send_with_id)


class RequestContextFilter(logging.Filter):
    """Injecte le contexte de requête dans chaque enregistrement (sans écraser l'existant)."""

    def filter(self, record: logging.LogRecord) -> bool:
        for attr, var in (
            ("request_id", request_id_var),
            ("client_ip", client_ip_var),
            ("http_method", http_method_var),
            ("http_path", http_path_var),
        ):
            if getattr(record, attr, None) is None:
                setattr(record, attr, var.get())
        if getattr(record, "user", None) is None:
            record.user = user_var.get()
        return True


def attach_context(logger: logging.Logger) -> logging.Logger:
    if not any(isinstance(f, RequestContextFilter) for f in logger.filters):
        logger.addFilter(RequestContextFilter())
    return logger


def log_event(
    logger: logging.Logger,
    level: int,
    event: str,
    message: str,
    *,
    http_status: int | None = None,
    user: str | None = None,
) -> None:
    """Émet un log d'événement normalisé avec http_status et duration_ms."""
    started = started_var.get()
    extra: dict = {"event": event, "http_status": http_status}
    if started is not None:
        extra["duration_ms"] = int((time.perf_counter() - started) * 1000)
    if user is not None:
        extra["user"] = user
    logger.log(level, message, extra=extra)


class ApiError(Exception):
    """Erreur métier rendue au format REST du contrat."""

    def __init__(self, status: int, code: str, message: str, headers: dict | None = None) -> None:
        self.status, self.code, self.message, self.headers = status, code, message, headers
        super().__init__(message)


def error_response(
    status: int, code: str, message: str, headers: dict | None = None
) -> JSONResponse:
    """Corps d'erreur du contrat : { "error": { code, message, request_id } }."""
    body = {"error": {"code": code, "message": message, "request_id": request_id_var.get()}}
    return JSONResponse(body, status_code=status, headers=headers)
