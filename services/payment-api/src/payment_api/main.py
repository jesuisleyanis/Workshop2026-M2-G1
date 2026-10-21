"""Application FastAPI du service payment-api (port interne 8001, réseau app).

Lancement : uvicorn payment_api.main:create_app --factory --port 8001
"""

import logging
import time
from collections.abc import Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, Path, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from resilience_common.logging import get_logger
from resilience_common.metrics import db_errors_total, instrument, transactions_total
from resilience_db.config import make_engine, make_session_factory
from resilience_db.migrate import upgrade
from resilience_db.models import Account, Transaction, User
from sqlalchemy import Engine, or_, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import aliased
from starlette.exceptions import HTTPException as StarletteHTTPException

from payment_api import beneficiaries, cards, limits, stats
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
from payment_api.schemas import (
    AccountOut,
    BeneficiaryIn,
    BeneficiaryOut,
    CardOut,
    CardPatch,
    LimitOut,
    ServiceStatusOut,
    SpendingOut,
    TransactionIn,
    TransactionOut,
)
from payment_api.security import missing_token, username_from_token
from payment_api.status import StatusCache


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


# Identifiant en chemin borné à l'INTEGER Postgres : au-delà, la BDD lèverait une DataError,
# traduite en 503 db_unavailable + db_errors_total, soit un faux signal d'incident pour le ML.
DbId = Annotated[int, Path(ge=1, le=2**31 - 1)]


def _as_seen_by(tx: Transaction, own_ids: set[int]) -> TransactionOut:
    # La catégorie est celle de l'émetteur : jamais divulguée au destinataire (#44).
    out = TransactionOut.model_validate(tx)
    return out if tx.src_account in own_ids else out.model_copy(update={"category": None})


def _db_reachable(session) -> bool:
    try:
        session.execute(text("SELECT 1"))
    except SQLAlchemyError:
        return False
    return True


def create_app(
    settings: Settings | None = None,
    engine: Engine | None = None,
    clock: Callable[[], float] = time.monotonic,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> FastAPI:
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
        if not _db_reachable(session):
            raise ApiError(503, "db_unavailable", "Database unreachable")
        return {"status": "ready"}

    # État public du service (bandeau client « perturbé → rétabli », #42) : sans auth, donc
    # aucun détail interne ; cache à vol unique (cf. status.py), limité par IP au WAF.
    def _probe_db() -> bool:
        with session_factory() as session:
            return _db_reachable(session)

    status_cache = StatusCache(_probe_db, settings.status_cache_s, clock)

    @app.get("/api/v1/status", response_model=ServiceStatusOut)
    def service_status():
        body = status_cache.get()
        return JSONResponse(body.model_dump(), status_code=200 if body.status == "ok" else 503)

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
                body.category,
                now(),
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
        own_ids = set(session.scalars(select(Account.id).where(Account.user_id == user.id)))
        rows = session.scalars(
            select(Transaction)
            .where(or_(Transaction.src_account.in_(own_ids), Transaction.dst_account.in_(own_ids)))
            .order_by(Transaction.id.desc())
            .limit(limit)
        ).all()
        return [_as_seen_by(t, own_ids) for t in rows]

    @app.get("/api/v1/transactions/{transaction_id}", response_model=TransactionOut)
    def get_transaction(
        transaction_id: DbId,
        user: User = Depends(current_user),
        session=Depends(get_session),
    ):
        src, dst = aliased(Account), aliased(Account)
        row = session.execute(
            select(Transaction, src.user_id, dst.user_id)
            .join(src, src.id == Transaction.src_account)
            .join(dst, dst.id == Transaction.dst_account)
            .where(Transaction.id == transaction_id)
        ).first()  # une seule requête : l'opération et ses deux titulaires
        if row is None or user.id not in (row[1], row[2]):
            # Ni émetteur ni destinataire : même 404 qu'un id inconnu (pas 403, anti-énumération),
            # mais tracé côté SOC (balayage d'ids = tentative d'IDOR).
            log_event(
                log,
                logging.WARNING,
                "transaction_access_denied",
                f"Transaction lookup denied ({'unknown' if row is None else 'foreign'})",
                http_status=404,
                user=user.username,
            )
            raise ApiError(404, "transaction_not_found", "Transaction not found")
        tx, sender, _ = row
        own = {tx.src_account} if sender == user.id else set()
        return _as_seen_by(tx, own)

    @app.get("/api/v1/limits", response_model=list[LimitOut])
    def list_limits(user: User = Depends(current_user), session=Depends(get_session)):
        return limits.limits_for(session, user, now())

    @app.get("/api/v1/stats/spending", response_model=SpendingOut)
    def spending_stats(
        period: Literal["week", "month"] = Query("month"),
        offset: int = Query(0, ge=-24, le=0),
        user: User = Depends(current_user),
        session=Depends(get_session),
    ):
        return stats.spending(session, user, period, now(), offset)

    # ---------------------------------------------------------------- cartes (#47)
    @app.get("/api/v1/cards", response_model=list[CardOut])
    def list_cards(user: User = Depends(current_user), session=Depends(get_session)):
        return cards.list_for(session, user)

    def _card_status(card_id: int, status: str, event: str, user: User, session):
        try:
            card, changed = cards.set_status(session, user, card_id, status)
        except Rejection as rej:
            raise ApiError(rej.status, rej.code, rej.message)
        if changed:  # idempotent : pas de second événement pour un état inchangé
            log_event(log, logging.INFO, event, f"Card {card.id} {status}", user=user.username)
        return card

    @app.post("/api/v1/cards/{card_id}/freeze", response_model=CardOut)
    def freeze_card(
        card_id: DbId, user: User = Depends(current_user), session=Depends(get_session)
    ):
        return _card_status(card_id, "frozen", "card_frozen", user, session)

    @app.post("/api/v1/cards/{card_id}/unfreeze", response_model=CardOut)
    def unfreeze_card(
        card_id: DbId, user: User = Depends(current_user), session=Depends(get_session)
    ):
        return _card_status(card_id, "active", "card_unfrozen", user, session)

    @app.patch("/api/v1/cards/{card_id}", response_model=CardOut)
    def update_card(
        card_id: DbId,
        body: CardPatch,
        user: User = Depends(current_user),
        session=Depends(get_session),
    ):
        changes = body.model_dump(exclude_unset=True)
        try:
            card = cards.update(session, user, card_id, changes)
        except Rejection as rej:
            raise ApiError(rej.status, rej.code, rej.message)
        log_event(
            log,
            logging.INFO,
            "card_settings_changed",
            f"Card {card.id} settings changed: {', '.join(sorted(changes))}",
            user=user.username,
        )
        return card

    # ---------------------------------------------------------------- bénéficiaires (#43)
    @app.get("/api/v1/beneficiaries", response_model=list[BeneficiaryOut])
    def list_beneficiaries(user: User = Depends(current_user), session=Depends(get_session)):
        return beneficiaries.list_for(session, user)

    @app.post("/api/v1/beneficiaries", response_model=BeneficiaryOut, status_code=201)
    def add_beneficiary(
        body: BeneficiaryIn, user: User = Depends(current_user), session=Depends(get_session)
    ):
        try:
            created = beneficiaries.add(session, user, body.display_name, body.iban_fake)
        except Rejection as rej:
            # Jamais l'IBAN saisi dans le log : seulement le motif (rafale = énumération).
            log_event(
                log,
                logging.WARNING,
                "beneficiary_rejected",
                f"Beneficiary rejected ({rej.code})",
                http_status=rej.status,
                user=user.username,
            )
            raise ApiError(rej.status, rej.code, rej.message)
        log_event(
            log,
            logging.INFO,
            "beneficiary_added",
            f"Beneficiary {created.id} added (account {created.account_id})",
            http_status=201,
            user=user.username,
        )
        return created

    @app.delete("/api/v1/beneficiaries/{beneficiary_id}", status_code=204)
    def delete_beneficiary(
        beneficiary_id: DbId,
        user: User = Depends(current_user),
        session=Depends(get_session),
    ):
        try:
            beneficiaries.remove(session, user, beneficiary_id)
        except Rejection as rej:
            raise ApiError(rej.status, rej.code, rej.message)
        log_event(
            log,
            logging.INFO,
            "beneficiary_removed",
            f"Beneficiary {beneficiary_id} removed",
            http_status=204,
            user=user.username,
        )
        return Response(status_code=204)

    return app
