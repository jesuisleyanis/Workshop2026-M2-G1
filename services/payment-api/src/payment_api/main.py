"""Application FastAPI du service payment-api (port interne 8001, réseau app).

Lancement : uvicorn payment_api.main:create_app --factory --port 8001
"""

import logging
import time
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from resilience_common.logging import get_logger
from resilience_common.metrics import db_errors_total, instrument, transactions_total
from resilience_db.config import make_engine, make_session_factory
from resilience_db.migrate import upgrade
from resilience_db.models import Account, Transaction, User
from sqlalchemy import Engine, or_, select, text
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException

from payment_api.config import SERVICE_NAME, Settings
from payment_api.ledger import Rejection, transfer
from payment_api.observability import (
    ApiError,
    RequestContextMiddleware,
    attach_context,
    error_response,
    log_event,
    request_id_var,
)
from payment_api.schemas import AccountOut, TransactionIn, TransactionOut
from payment_api.security import missing_token, username_from_token


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


def create_app(settings: Settings | None = None, engine: Engine | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    engine = engine or make_engine()
    session_factory = make_session_factory(engine)
    log = attach_context(
        get_logger(SERVICE_NAME, getattr(logging, settings.log_level, logging.INFO))
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        if settings.run_migrations:
            _migrate_with_retry(engine, log)
        yield

    app = FastAPI(
        title="RESILIENCE-ALPHA payment-api",
        version="1.0.0",
        lifespan=lifespan,
        docs_url="/docs" if settings.enable_docs else None,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.enable_docs else None,
    )
    app.state.session_factory = session_factory
    app.add_middleware(RequestContextMiddleware, trusted_proxy_hops=settings.trusted_proxy_hops)
    instrument(app, SERVICE_NAME)

    # ---------------------------------------------------------------- dépendances
    bearer = HTTPBearer(auto_error=False)

    def get_session():
        with session_factory() as session:
            yield session

    def current_user(
        creds: HTTPAuthorizationCredentials | None = Depends(bearer),
        session=Depends(get_session),
    ) -> User:
        """Dépendance commune : toutes les routes métier exigent un JWT valide."""
        if creds is None:
            raise missing_token()
        username = username_from_token(creds.credentials, settings.jwt_secret)
        user = session.scalar(select(User).where(User.username == username))
        if user is None:  # JWT valide mais compte supprimé
            raise ApiError(401, "invalid_token", "Invalid token", {"WWW-Authenticate": "Bearer"})
        return user

    # ---------------------------------------------------------------- erreurs
    @app.exception_handler(ApiError)
    async def _api_error(_req: Request, exc: ApiError):
        return error_response(exc.status, exc.code, exc.message, exc.headers)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_req: Request, exc: StarletteHTTPException):
        return error_response(exc.status_code, f"http_{exc.status_code}", str(exc.detail))

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_req: Request, exc: RequestValidationError):
        fields = ", ".join(".".join(str(p) for p in e["loc"][1:]) or "body" for e in exc.errors())
        return error_response(422, "validation_error", f"Invalid request fields: {fields}")

    @app.exception_handler(SQLAlchemyError)
    async def _db_error(_req: Request, exc: SQLAlchemyError):
        db_errors_total.inc()
        log_event(
            log,
            logging.ERROR,
            "db_error",
            f"Database error: {type(exc).__name__}",  # jamais la requête SQL ni ses paramètres
            http_status=503,
        )
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
        # Sonde : n'incrémente PAS resilience_db_errors_total (réservé au trafic métier).
        try:
            session.execute(text("SELECT 1"))
        except SQLAlchemyError:
            raise ApiError(503, "db_unavailable", "Database unreachable")
        return {"status": "ready"}

    # ---------------------------------------------------------------- API métier
    @app.get("/api/v1/accounts", response_model=list[AccountOut])
    def list_accounts(user: User = Depends(current_user), session=Depends(get_session)):
        return session.scalars(
            select(Account).where(Account.user_id == user.id).order_by(Account.id)
        ).all()

    @app.post("/api/v1/transactions", response_model=TransactionOut, status_code=201)
    def create_transaction(
        body: TransactionIn, user: User = Depends(current_user), session=Depends(get_session)
    ):
        try:
            tx = transfer(
                session,
                user,
                body.src_account,
                body.dst_account,
                body.amount_cents,
                request_id_var.get(),
            )
        except Rejection as rej:
            transactions_total.labels(result="rejected").inc()
            log_event(
                log,
                logging.WARNING,
                "transaction_rejected",
                f"Transaction rejected ({rej.code}): {rej.message}",
                http_status=rej.status,
                user=user.username,
            )
            raise ApiError(rej.status, rej.code, rej.message)
        transactions_total.labels(result="created").inc()
        log_event(
            log,
            logging.INFO,
            "transaction_created",
            f"Transaction {tx.id} accepted",
            http_status=201,
            user=user.username,
        )
        return tx

    @app.get("/api/v1/transactions", response_model=list[TransactionOut])
    def list_transactions(
        limit: int = Query(50, ge=1, le=200),
        user: User = Depends(current_user),
        session=Depends(get_session),
    ):
        own = select(Account.id).where(Account.user_id == user.id)
        return session.scalars(
            select(Transaction)
            .where(or_(Transaction.src_account.in_(own), Transaction.dst_account.in_(own)))
            .order_by(Transaction.id.desc())
            .limit(limit)
        ).all()

    return app
