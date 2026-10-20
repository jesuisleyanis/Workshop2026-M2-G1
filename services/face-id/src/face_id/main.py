"""Application FastAPI du service face-id (port interne 8006, réseau app + data).

Reconnaissance 1:1 (identifiant <-> visage) par SÉQUENCE de 3 poses (face, gauche, droite) +
enrôlement des habilitations biométriques.
Lancement : uvicorn face_id.main:create_app --factory --port 8006

RGPD : gabarits et vignettes d'enrôlement sont scellés (AES-256-GCM, clé FACE_DATA_KEY, AAD lié
à l'utilisateur) avant d'atteindre la base ; la liste des enrôlements ne renvoie aucune donnée
biométrique ; la consultation des vignettes (admin) est journalisée. Aucune image, aucun
embedding n'apparaît dans les logs. Erreurs au format du contrat : {"error": {code, message}}.
"""

from __future__ import annotations

import base64
import binascii
import hmac
import logging
import time
from collections.abc import Callable

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator
from resilience_common.logging import get_logger
from resilience_common.metrics import (
    face_enrollments,
    face_verifications_total,
    face_verify_duration_seconds,
    instrument,
)
from resilience_db.config import make_engine, make_session_factory
from resilience_db.migrate import upgrade
from sqlalchemy import Engine, text
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException

from face_id import SERVICE_NAME
from face_id.config import Settings
from face_id.crypto import (
    SealError,
    Sealer,
    pack_photos,
    pack_templates,
    unpack_photos,
    unpack_templates,
)
from face_id.enrollment import (
    EnrollmentRejected,
    PoseIssue,
    build_templates,
    thumbnail,
    verify_sequence,
)
from face_id.poses import POSES
from face_id.recognizer import Recognizer, build_recognizer
from face_id.store import EnrollmentStore, UnknownUserError

log = get_logger(SERVICE_NAME)


# Plafond anti-DoS (~1 Mo d'image en base64) par image : une photo de visage est bien en deçà.
_MAX_IMAGE_B64 = 1_500_000

# Anomalies de lecture d'un blob stocké (ligne v1 non scellée, blob altéré, gabarit incompatible).
_UNREADABLE = (SealError, ValueError, KeyError, TypeError)


class Frame(BaseModel):
    pose: str = Field(min_length=1, max_length=16)
    image_b64: str = Field(min_length=1, max_length=_MAX_IMAGE_B64)


class VerifyRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    frames: list[Frame] = Field(min_length=3, max_length=3)

    @field_validator("frames")
    @classmethod
    def _three_distinct_poses(cls, v: list[Frame]) -> list[Frame]:
        if sorted(f.pose for f in v) != sorted(POSES):
            raise ValueError("trois poses distinctes (face, gauche, droite) requises")
        return v


class VerifyResponse(BaseModel):
    # Ni score ni motif d'échec dans la réponse (anti hill-climbing) : motifs dans les logs.
    match: bool
    model_version: str


class EnrollRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    enrolled_by: str = Field(default="system", max_length=64)
    poses: dict[str, str]

    @field_validator("poses")
    @classmethod
    def _known_poses_bounded(cls, v: dict[str, str]) -> dict[str, str]:
        if not set(v) <= set(POSES):
            raise ValueError("pose inconnue (face, gauche, droite attendues)")
        if any(len(img) > _MAX_IMAGE_B64 for img in v.values()):
            raise ValueError("image trop volumineuse")
        return v


class EnrollResponse(BaseModel):
    enrolled: bool
    model_version: str
    poses: list[str]


def _api_error(
    status: int, code: str, message: str, details: list[dict[str, str]] | None = None
) -> HTTPException:
    detail: dict = {"code": code, "message": message}
    if details is not None:
        detail["details"] = details
    return HTTPException(status_code=status, detail=detail)


def _error_body(code: str, message: str, details: list | None = None) -> dict:
    error: dict = {"code": code, "message": message}
    if details is not None:
        error["details"] = details
    return {"error": error}


def _decode_image(image_b64: str) -> bytes:
    try:
        return base64.b64decode(image_b64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise _api_error(422, "invalid_image", "image_b64 invalide (base64 attendu)") from exc


def _templates_aad(username: str) -> bytes:
    return f"{username}|templates".encode()


def _photos_aad(username: str) -> bytes:
    return f"{username}|photos".encode()


def create_app(
    settings: Settings | None = None,
    engine: Engine | None = None,
    recognizer: Recognizer | None = None,
    thumbnailer: Callable[[bytes], bytes] | None = None,
) -> FastAPI:
    settings = settings or Settings.from_env()
    log.setLevel(getattr(logging, settings.log_level, logging.INFO))
    sealer = Sealer.from_b64(settings.face_data_key)  # échoue au démarrage si la clé est invalide
    make_thumbnail = thumbnailer or thumbnail
    engine = engine or make_engine()
    if settings.run_migrations:
        upgrade(engine)
    session_factory = make_session_factory(engine)
    store = EnrollmentStore(session_factory)
    recognizer = recognizer or build_recognizer(settings.recognizer_backend, settings.threshold)

    app = FastAPI(title="RESILIENCE face-id", version="2.0.0", docs_url=None, redoc_url=None)
    app.state.store = store
    app.state.recognizer = recognizer
    instrument(app, SERVICE_NAME)

    try:
        face_enrollments.set(store.count())
    except Exception as exc:  # noqa: BLE001 - la métrique ne doit jamais empêcher le démarrage
        log.debug(
            "Initialisation de la jauge d'enrôlements différée (%s)",
            type(exc).__name__,
            extra={"event": "db_error"},
        )

    # ---------------------------------------------------------------- erreurs (format contrat)
    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_req: Request, exc: StarletteHTTPException):
        if isinstance(exc.detail, dict) and "code" in exc.detail:
            body = _error_body(
                exc.detail["code"], exc.detail.get("message", ""), exc.detail.get("details")
            )
        else:
            body = _error_body(f"http_{exc.status_code}", str(exc.detail))
        return JSONResponse(body, status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_req: Request, exc: RequestValidationError):
        # Jamais d'écho de `input` : il contient des images en base64.
        fields = ", ".join(".".join(str(p) for p in e["loc"][1:]) or "body" for e in exc.errors())
        return JSONResponse(
            _error_body("validation_error", f"Requête invalide: {fields}"), status_code=422
        )

    @app.exception_handler(Exception)
    async def _unhandled(_req: Request, exc: Exception):
        # Type seul : jamais de contenu d'image. Tout log porte un `event` réservé (contrat §1).
        event = "db_error" if isinstance(exc, SQLAlchemyError) else "face_verify_error"
        log.error("Erreur non gérée: %s", type(exc).__name__, extra={"event": event})
        return JSONResponse(_error_body("internal_error", "Erreur interne"), status_code=500)

    def require_internal_token(x_internal_token: str = Header(default="")) -> None:
        # compare_digest exige des bytes pour tolérer un header non-ASCII (sinon TypeError -> 500).
        if not hmac.compare_digest(x_internal_token.encode(), settings.internal_token.encode()):
            raise _api_error(401, "internal_token_invalid", "Jeton interne invalide ou absent")

    # ---------------------------------------------------------------- sondes
    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.get("/ready")
    def ready():
        problems = []
        if app.state.recognizer is None:
            problems.append("recognizer non chargé")
        try:
            with session_factory() as s:
                s.execute(text("SELECT 1"))
        except Exception as exc:  # noqa: BLE001
            # Type seul dans le log (une URL de connexion peut figurer dans le message d'erreur).
            log.warning(
                "Readiness : base injoignable (%s)", type(exc).__name__, extra={"event": "db_error"}
            )
            problems.append("db injoignable")
        if problems:
            return JSONResponse(status_code=503, content={"status": "not_ready", "problems": problems})
        return {"status": "ready"}

    # ---------------------------------------------------------------- vérification
    def _finish_verify(start: float, result: str, username: str, reason: str) -> VerifyResponse:
        """Métrique + log d'une vérification ; le motif n'est que dans le log."""
        face_verifications_total.labels(result).inc()
        face_verify_duration_seconds.observe(time.perf_counter() - start)
        if result == "match":
            log.info("Visage reconnu", extra={"event": "face_verify_match", "user": username})
        elif result == "nomatch":
            log.info(
                f"Visage non reconnu (motif: {reason})",
                extra={"event": "face_verify_nomatch", "user": username},
            )
        else:
            log.warning(
                f"Vérification impossible (motif: {reason})",
                extra={"event": "face_verify_error", "user": username},
            )
        return VerifyResponse(match=result == "match", model_version=recognizer.model_version)

    @app.post(
        "/api/v1/verify",
        response_model=VerifyResponse,
        dependencies=[Depends(require_internal_token)],
    )
    def verify(req: VerifyRequest) -> VerifyResponse:
        start = time.perf_counter()
        frames = [(f.pose, _decode_image(f.image_b64)) for f in req.frames]
        stored = store.get(req.username)
        if stored is None:
            # Identifiant inconnu ou non enrôlé => non-correspondance
            # (anti-énumération : même réponse qu'un visage qui ne correspond pas).
            return _finish_verify(start, "nomatch", req.username, "not_enrolled")
        if stored.model_version != recognizer.model_version:
            # Gabarits issus d'un AUTRE modèle (ou ligne v1) : comparaison invalide. Journalisé
            # explicitement (réenrôlement requis) plutôt que confondu avec un vrai no-match.
            return _finish_verify(start, "error", req.username, "model_version_mismatch")
        try:
            templates = unpack_templates(
                sealer.open(stored.templates_blob, _templates_aad(req.username))
            )
            match, reason = verify_sequence(recognizer, templates, frames)
        except _UNREADABLE:
            return _finish_verify(start, "error", req.username, "templates_unreadable")
        return _finish_verify(start, "match" if match else "nomatch", req.username, reason)

    # ---------------------------------------------------------------- enrôlement
    def _reject_enrollment(username: str, issues: dict[str, str]) -> HTTPException:
        ordered = [PoseIssue(p, issues[p]) for p in POSES if p in issues]
        summary = ", ".join(f"{i.pose}:{i.reason}" for i in ordered)
        log.warning(
            f"Enrôlement refusé ({summary})",
            extra={"event": "face_enrollment_rejected", "user": username},
        )
        return _api_error(
            422,
            "enrollment_rejected",
            "Série de photos refusée : reprendre les poses indiquées",
            [{"pose": i.pose, "reason": i.reason} for i in ordered],
        )

    @app.post(
        "/api/v1/enroll",
        response_model=EnrollResponse,
        dependencies=[Depends(require_internal_token)],
    )
    def enroll(req: EnrollRequest) -> EnrollResponse:
        if not store.user_exists(req.username):
            raise _api_error(404, "unknown_user", "Utilisateur inconnu")
        images: dict[str, bytes] = {}
        issues: dict[str, str] = {}
        for pose in POSES:
            raw = req.poses.get(pose)
            if raw is None:
                continue  # signalée « missing » par build_templates
            try:
                images[pose] = _decode_image(raw)
            except HTTPException:
                issues[pose] = "invalid_image"
        try:
            templates = build_templates(recognizer, images)
        except EnrollmentRejected as exc:
            for issue in exc.issues:
                issues.setdefault(issue.pose, issue.reason)
            raise _reject_enrollment(req.username, issues) from exc
        # Ici toutes les poses sont présentes et valides : on ne garde que des vignettes.
        thumbs: dict[str, bytes] = {}
        for pose in POSES:
            try:
                thumbs[pose] = make_thumbnail(images[pose])
            except ValueError:
                issues[pose] = "invalid_image"
        if issues:
            raise _reject_enrollment(req.username, issues)

        try:
            store.upsert(
                req.username,
                sealer.seal(pack_templates(templates), _templates_aad(req.username)),
                sealer.seal(pack_photos(thumbs), _photos_aad(req.username)),
                ",".join(POSES),
                recognizer.model_version,
                req.enrolled_by,
            )
        except UnknownUserError as exc:
            raise _api_error(404, "unknown_user", "Utilisateur inconnu") from exc
        face_enrollments.set(store.count())
        log.info("Visage enrôlé", extra={"event": "face_enrolled", "user": req.username})
        return EnrollResponse(
            enrolled=True, model_version=recognizer.model_version, poses=list(POSES)
        )

    @app.delete(
        "/api/v1/enroll/{username}",
        status_code=204,
        dependencies=[Depends(require_internal_token)],
    )
    def revoke(username: str):
        if not store.delete(username):
            raise _api_error(404, "not_enrolled", "Aucun enrôlement pour cet utilisateur")
        face_enrollments.set(store.count())
        log.info("Enrôlement révoqué", extra={"event": "face_enrollment_revoked", "user": username})
        return Response(status_code=204)  # corps vide : un JSON null casse sous uvicorn (204)

    @app.get("/api/v1/enrollments", dependencies=[Depends(require_internal_token)])
    def enrollments() -> list[dict]:
        # `usable` = vérifiable par le modèle chargé (auth n'en compte que celles-là comme enrôlées).
        return store.list(recognizer.model_version)

    @app.get(
        "/api/v1/enrollments/{username}/photos", dependencies=[Depends(require_internal_token)]
    )
    def photos(username: str, viewer: str = Query(min_length=1, max_length=64)) -> dict:
        stored = store.get(username)
        if stored is None or stored.photos_blob is None:  # non enrôlé, ou ligne v1 sans photos
            raise _api_error(404, "not_enrolled", "Aucune photo d'enrôlement pour cet utilisateur")
        try:
            thumbs = unpack_photos(sealer.open(stored.photos_blob, _photos_aad(username)))
        except _UNREADABLE as exc:
            log.warning(
                "Photos d'enrôlement illisibles (réenrôlement requis)",
                extra={"event": "face_verify_error", "user": username},
            )
            raise _api_error(404, "photos_unavailable", "Photos illisibles : réenrôler") from exc
        # Piste d'audit RGPD : qui a consulté les photos de qui (jamais le contenu).
        log.info(
            f"Photos d'enrôlement consultées par {viewer}",
            extra={"event": "face_photos_viewed", "user": username},
        )
        return {"photos": {p: base64.b64encode(thumbs[p]).decode() for p in POSES if p in thumbs}}

    return app
