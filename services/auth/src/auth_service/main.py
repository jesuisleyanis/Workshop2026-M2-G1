"""Application FastAPI du service auth (port interne 8002, réseau app).

Lancement : uvicorn auth_service.main:create_app --factory --port 8002
"""

import logging
import time
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from resilience_common.logging import get_logger
from resilience_common.metrics import auth_logins_total, auth_rate_limited_total, instrument
from resilience_db.config import make_engine, make_session_factory
from resilience_db.factories import new_fake_iban
from resilience_db.migrate import upgrade
from resilience_db.models import Account, User
from resilience_db.passwords import DUMMY_HASH, hash_password, verify_password
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from sqlalchemy import Engine, select, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException

from auth_service.backoffice import (
    FaceVerifier,
    HttpFaceVerifier,
    LedNotifier,
    LogLedNotifier,
    add_backoffice_auth,
)
from auth_service.challenge import ChallengeStore, LockoutStore
from auth_service.config import SERVICE_NAME, Settings
from auth_service.observability import (
    ApiError,
    RequestContextMiddleware,
    attach_context,
    client_ip_var,
    error_response,
    log_event,
)
from auth_service.ratelimit import DynamicRateLimit
from auth_service.schemas import (
    LoginRequest,
    RateLimitOut,
    RegisterRequest,
    TightenRequest,
    TokenOut,
    UserOut,
)
from auth_service.security import create_access_token, internal_token_matches


def _migrate_with_retry(engine: Engine, log: logging.Logger, attempts: int = 5) -> None:
    for attempt in range(1, attempts + 1):
        try:
            upgrade(engine)
            return
        except SQLAlchemyError:
            if attempt == attempts:
                raise
            log.warning("DB not ready for migrations (attempt %d/%d)", attempt, attempts)
            time.sleep(2)


def create_app(
    settings: Settings | None = None,
    engine: Engine | None = None,
    *,
    face_verifier: FaceVerifier | None = None,
    led_notifier: LedNotifier | None = None,
    clock=None,
) -> FastAPI:
    settings = settings or Settings.from_env()
    engine = engine or make_engine()
    session_factory = make_session_factory(engine)
    log = attach_context(
        get_logger(SERVICE_NAME, getattr(logging, settings.log_level, logging.INFO))
    )
    if not settings.backoffice_face_required:
        # Mode dégradé : le mot de passe seul suffit pour un compte privilégié (répétitions de
        # démo uniquement). À ne jamais positionner dans le compose de démo notée.
        log.warning("BACKOFFICE_FACE_REQUIRED=false : facteur visage DÉSACTIVÉ (mode dégradé)")

    rate = DynamicRateLimit(settings.login_rate_limit)
    limiter = Limiter(
        key_func=lambda request: client_ip_var.get() or "unknown", storage_uri="memory://"
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        if settings.run_migrations:
            _migrate_with_retry(engine, log)
        yield

    docs = "/docs" if settings.enable_docs else None
    app = FastAPI(
        title="RESILIENCE-ALPHA auth",
        version="1.0.0",
        lifespan=lifespan,
        docs_url=docs,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.enable_docs else None,
    )
    app.state.limiter = limiter
    app.state.rate = rate
    app.state.session_factory = session_factory
    app.add_middleware(RequestContextMiddleware, trusted_proxy_hops=settings.trusted_proxy_hops)
    instrument(app, SERVICE_NAME)

    # ---------------------------------------------------------------- dépendances
    def get_session():
        with session_factory() as session:
            yield session

    def require_internal_token(x_internal_token: str | None = Header(default=None)) -> None:
        if not internal_token_matches(x_internal_token, settings.internal_token):
            log.warning("Rejected internal call with invalid token")
            raise ApiError(401, "invalid_internal_token", "Invalid or missing internal token")

    # ---------------------------------------------------------------- erreurs
    @app.exception_handler(ApiError)
    async def _api_error(_req: Request, exc: ApiError):
        return error_response(exc.status, exc.code, exc.message, exc.headers)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_req: Request, exc: StarletteHTTPException):
        return error_response(exc.status_code, f"http_{exc.status_code}", str(exc.detail))

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_req: Request, exc: RequestValidationError):
        # Pas d'écho de `input` : il peut contenir un mot de passe.
        fields = ", ".join(".".join(str(p) for p in e["loc"][1:]) or "body" for e in exc.errors())
        return error_response(422, "validation_error", f"Invalid request fields: {fields}")

    @app.exception_handler(RateLimitExceeded)
    async def _rate_limited(_req: Request, _exc: RateLimitExceeded):
        auth_rate_limited_total.inc()
        log_event(
            log,
            logging.WARNING,
            "auth_rate_limited",
            f"Rate limit exceeded ({rate.value}) for {client_ip_var.get()}",
            http_status=429,
        )
        return error_response(
            429, "rate_limited", "Too many requests", {"Retry-After": str(rate.retry_after_seconds)}
        )

    @app.exception_handler(SQLAlchemyError)
    async def _db_error(_req: Request, exc: SQLAlchemyError):
        # `db_error` / resilience_db_errors_total sont réservés à payment-api (contrat).
        log.error("Database error: %s", type(exc).__name__)
        return error_response(503, "db_unavailable", "Database unavailable")

    @app.exception_handler(Exception)
    async def _unhandled(_req: Request, exc: Exception):
        log.error("Unhandled exception", exc_info=exc)
        return error_response(500, "internal_error", "Internal server error")

    # ---------------------------------------------------------------- sondes
    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/ready")
    def ready(session=Depends(get_session)):
        try:
            session.execute(text("SELECT 1"))
        except SQLAlchemyError:
            raise ApiError(503, "db_unavailable", "Database unreachable")
        return {"status": "ready"}

    # ---------------------------------------------------------------- API métier
    @app.post("/api/v1/register", response_model=UserOut, status_code=201)
    @limiter.limit(settings.register_rate_limit)
    def register(request: Request, body: RegisterRequest, session=Depends(get_session)):
        if session.scalar(select(User.id).where(User.username == body.username)) is not None:
            raise ApiError(409, "username_taken", "Username already exists")
        user = User(username=body.username, password_hash=hash_password(body.password))
        user.accounts.append(
            Account(
                iban_fake=new_fake_iban(),
                balance_cents=settings.register_initial_balance_cents,
                currency="EUR",
            )
        )
        session.add(user)
        try:
            session.commit()
        except IntegrityError:  # course : même username créé entre le SELECT et l'INSERT
            session.rollback()
            raise ApiError(409, "username_taken", "Username already exists")
        return UserOut(id=user.id, username=user.username)

    @app.post("/api/v1/login", response_model=TokenOut)
    @limiter.limit(rate)
    def login(request: Request, body: LoginRequest, session=Depends(get_session)):
        user = session.scalar(select(User).where(User.username == body.username))
        # Vérification systématique (hash factice si inconnu) : temps de réponse constant.
        valid = verify_password(body.password, user.password_hash if user else DUMMY_HASH)
        if user is None or not valid:
            auth_logins_total.labels(result="failed").inc()
            log_event(
                log,
                logging.WARNING,
                "auth_login_failed",
                f"Invalid credentials for user {body.username}",
                http_status=401,
                user=body.username,
            )
            raise ApiError(401, "invalid_credentials", "Invalid credentials")
        token, expires_in = create_access_token(user.username, settings.jwt_secret)
        auth_logins_total.labels(result="success").inc()
        log_event(
            log,
            logging.INFO,
            "auth_login_success",
            f"User {user.username} logged in",
            http_status=200,
            user=user.username,
        )
        return TokenOut(access_token=token, expires_in=expires_in)

    # ---------------------------------------------------------------- API interne (remédiation)
    # Jamais routée par le WAF ; protégée en plus par INTERNAL_TOKEN.
    @app.post(
        "/internal/tighten-rate-limit",
        response_model=RateLimitOut,
        dependencies=[Depends(require_internal_token)],
    )
    def tighten_rate_limit(body: TightenRequest):
        before, after = rate.tighten(body.factor)
        log.warning("Login rate limit tightened %s -> %s (factor %s)", before, after, body.factor)
        return RateLimitOut(previous_limit=before, current_limit=after)

    @app.post(
        "/internal/reset-rate-limit",
        response_model=RateLimitOut,
        dependencies=[Depends(require_internal_token)],
    )
    def reset_rate_limit():
        before, after = rate.reset()
        log.info("Login rate limit reset %s -> %s", before, after)
        return RateLimitOut(previous_limit=before, current_limit=after)

    # ---------------------------------------------------------------- back-office à étapes
    store_kwargs = {"clock": clock} if clock is not None else {}
    challenges = ChallengeStore(settings.backoffice_challenge_ttl, **store_kwargs)
    lockouts = LockoutStore(
        settings.backoffice_max_attempts,
        settings.backoffice_lockout_seconds,
        failure_window_seconds=settings.backoffice_failure_window,
        **store_kwargs,
    )
    add_backoffice_auth(
        app,
        settings=settings,
        session_factory=session_factory,
        log=log,
        face_verifier=face_verifier
        or HttpFaceVerifier(settings.face_id_url, settings.face_internal_token),
        led=led_notifier or LogLedNotifier(log),
        challenges=challenges,
        lockouts=lockouts,
        limiter=limiter,
    )
    app.state.challenges = challenges
    app.state.lockouts = lockouts

    return app
