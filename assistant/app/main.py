"""API FastAPI de l'assistant opérateur RAG.

FRONTIÈRE DE SÉCURITÉ : ce service est en LECTURE DOCUMENTAIRE SEULE. Il ne déclenche aucune
action, n'appelle jamais l'API du moteur de remédiation, ne monte pas de socket Docker et ne
possède aucun identifiant privilégié. Voir assistant/CAHIER-DES-CHARGES.md.
"""

from __future__ import annotations

import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from langchain_chroma import Chroma
from langchain_core.language_models.chat_models import BaseChatModel
from pydantic import BaseModel, Field
from resilience_common import get_logger
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import rag
from app import store as store_mod
from app.config import SERVICE_NAME, Settings
from app.embeddings import backend_id
from app.indexer import build_index
from app.llm import build_llm, ollama_reachable

STATIC_DIR = Path(__file__).parent / "static"
log = get_logger(SERVICE_NAME)


class Source(BaseModel):
    doc: str
    extrait: str
    section: str = ""
    kind: str = "doc"
    score: float = 0.0


class AskRequest(BaseModel):
    question: str = Field(min_length=3)


class AskResponse(BaseModel):
    answer: str
    sources: list[Source]
    degraded: bool = False  # True : Ollama indisponible, seuls les passages sont renvoyés
    model: str = ""


def _error(request: Request, status: int, code: str, message: str) -> JSONResponse:
    rid = getattr(request.state, "request_id", None)
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message, "request_id": rid}})


def create_app(
    settings: Settings | None = None,
    *,
    store: Chroma | None = None,
    llm: BaseChatModel | None = None,
) -> FastAPI:
    """Fabrique l'application. `store` et `llm` sont injectables (tests, mocks)."""
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.store, app.state.store_error = store, None
        app.state.llm = llm
        try:
            if app.state.store is None:
                app.state.store = store_mod.open_store(settings)
                if store_mod.count(app.state.store) == 0 and settings.auto_index and store_mod.sources_available(settings):
                    build_index(settings)
                    app.state.store = store_mod.open_store(settings)
        except Exception as exc:  # Chroma illisible / embeddings indisponibles : /ready répondra 503
            app.state.store_error = f"{type(exc).__name__}: {exc}"
            log.error(f"Chroma non chargé : {app.state.store_error}", extra={"event": "assistant_store_error"})
        if app.state.llm is None:
            app.state.llm = build_llm(settings)  # construction paresseuse : aucune requête réseau ici
        yield

    app = FastAPI(title="RESILIENCE-ALPHA - Assistant opérateur (RAG, lecture seule)", version="1.0.0", lifespan=lifespan)

    if settings.metrics_enabled:
        from resilience_common.metrics import instrument

        instrument(app, SERVICE_NAME)

    # ------------------------------------------------------------------ middleware / erreurs
    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request.state.request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
        started = time.perf_counter()
        response = await call_next(request)
        duration_ms = int((time.perf_counter() - started) * 1000)
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        ancestors = " ".join(["'self'", *settings.frame_ancestors.split()])
        response.headers["Content-Security-Policy"] = (
            f"default-src 'self'; frame-ancestors {ancestors}; base-uri 'none'; form-action 'self'"
        )
        if request.url.path not in {"/health", "/ready", "/metrics"}:
            log.info(
                f"{request.method} {request.url.path} -> {response.status_code}",
                extra={
                    "event": "assistant_http_request",
                    "request_id": request.state.request_id,
                    "client_ip": (request.headers.get("x-forwarded-for") or (request.client.host if request.client else "")).split(",")[0].strip() or None,
                    "http_method": request.method,
                    "http_path": request.url.path,
                    "http_status": response.status_code,
                    "duration_ms": duration_ms,
                },
            )
        return response

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException):
        return _error(request, exc.status_code, "http_error", str(exc.detail))

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        return _error(request, 422, "invalid_request", "Requête invalide : 'question' (texte, 3 caractères minimum) attendu.")

    # ------------------------------------------------------------------ sondes
    def _index_state() -> tuple[bool, str, int]:
        st = app.state.store
        if st is None:
            return False, app.state.store_error or "Chroma non chargé", 0
        try:
            n = store_mod.count(st)
            stored = store_mod.stored_backend(st)
        except Exception as exc:
            return False, f"{type(exc).__name__}: {exc}", 0
        if n == 0:
            return False, "index vide : lancer `python -m app.indexer`", 0
        if stored and stored != backend_id(settings):
            return False, f"embeddings de l'index ({stored}) != configuration ({backend_id(settings)}) : ré-indexer", n
        return True, "ok", n

    @app.get("/health", tags=["sondes"])
    def health():
        """Liveness : le process répond."""
        return {"status": "ok", "service": SERVICE_NAME}

    @app.get("/ready", tags=["sondes"])
    def ready():
        """Readiness : prêt = index Chroma chargé et non vide.

        Ollama est SONDÉ mais son absence est TOLÉRÉE (mode dégradé : /ask renvoie les passages
        sans synthèse). Elle n'entraîne donc pas de 503.
        """
        ok, detail, n = _index_state()
        llm_up = ollama_reachable(settings)
        body = {
            "status": "ready" if ok else "not_ready",
            "mode": "nominal" if llm_up else "degraded",
            "chroma": {"loaded": ok, "chunks": n, "detail": detail, "embeddings": backend_id(settings)},
            "ollama": {"reachable": llm_up, "base_url": settings.ollama_base_url, "model": settings.ollama_model},
        }
        return JSONResponse(status_code=200 if ok else 503, content=body)

    # ------------------------------------------------------------------ API métier (lecture seule)
    @app.post("/api/v1/ask", response_model=AskResponse, tags=["assistant"])
    def ask(body: AskRequest, request: Request):
        """Répond à une question documentaire. NE DÉCLENCHE AUCUNE ACTION."""
        rid = request.state.request_id
        question = body.question.strip()
        if len(question) > settings.max_question_chars:
            return _error(request, 422, "question_too_long", f"Question limitée à {settings.max_question_chars} caractères.")
        ok, detail, _ = _index_state()
        if not ok:
            return _error(request, 503, "index_not_ready", detail)

        passages = [p for p in rag.retrieve(app.state.store, question, settings.top_k) if p.score >= settings.min_score]
        sources = [Source(**p.as_source()) for p in passages]
        degraded = False
        if not passages:
            answer = "Je n'ai trouvé aucun passage pertinent dans la documentation indexée pour cette question."
        else:
            try:
                answer = rag.generate(app.state.llm, question, passages)
            except Exception as exc:  # Ollama absent / timeout / modèle non tiré : mode dégradé documenté
                degraded = True
                log.warning(
                    f"LLM indisponible, mode dégradé ({type(exc).__name__})",
                    extra={"event": "assistant_llm_unavailable", "request_id": rid},
                )
                answer = (
                    "Mode dégradé : le modèle local (Ollama) est indisponible, aucune synthèse n'a pu être générée. "
                    "Voici les passages documentaires les plus pertinents (sources ci-dessous)."
                )
        log.info(
            f"Question traitée (len={len(question)}, sources={len(sources)}, degraded={degraded})",
            extra={"event": "assistant_question_answered", "request_id": rid},
        )
        return AskResponse(answer=answer, sources=sources, degraded=degraded, model=settings.ollama_model)

    # ------------------------------------------------------------------ UI
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/", include_in_schema=False)
    def ui():
        return FileResponse(STATIC_DIR / "index.html")

    return app


app = create_app()
