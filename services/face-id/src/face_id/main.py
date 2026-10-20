"""Application FastAPI du service face-id (port interne 8006, réseau app + data).

Reconnaissance 1:1 (identifiant <-> visage) + enrôlement des habilitations biométriques.
Lancement : uvicorn face_id.main:create_app --factory --port 8006

RGPD : aucune image n'est persistée ; seul l'embedding (vecteur) l'est, et la liste des
enrôlements ne renvoie jamais de donnée biométrique.
"""

from __future__ import annotations

import base64
import binascii
import hmac
import logging
import time

from fastapi import Depends, FastAPI, Header, HTTPException, Response
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

from face_id import SERVICE_NAME
from face_id.config import Settings
from face_id.recognizer import (
    NoFaceError,
    Recognizer,
    build_recognizer,
    cosine_similarity,
    deserialize_embedding,
    serialize_embedding,
)
from face_id.store import EnrollmentStore, UnknownUserError

log = get_logger(SERVICE_NAME)


# Plafond anti-DoS (~1 Mo d'image en base64) : une photo de visage est bien en deçà.
_MAX_IMAGE_B64 = 1_500_000


class VerifyRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    image_b64: str = Field(min_length=1, max_length=_MAX_IMAGE_B64)


class VerifyResponse(BaseModel):
    # Le score n'est PAS renvoyé (évite le hill-climbing) : il reste dans les logs/métriques.
    match: bool
    model_version: str


class EnrollRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    images_b64: list[str] = Field(min_length=1, max_length=10)
    enrolled_by: str = Field(default="system", max_length=64)

    @field_validator("images_b64")
    @classmethod
    def _bound_image_sizes(cls, v: list[str]) -> list[str]:
        if any(len(img) > _MAX_IMAGE_B64 for img in v):
            raise ValueError("image trop volumineuse")
        return v


class EnrollResponse(BaseModel):
    enrolled: bool
    quality: float
    model_version: str


def _decode_image(image_b64: str) -> bytes:
    try:
        return base64.b64decode(image_b64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(status_code=422, detail="image_b64 invalide") from exc


def _mean(vectors: list[list[float]]) -> list[float]:
    n = len(vectors)
    return [sum(col) / n for col in zip(*vectors, strict=True)]


def create_app(
    settings: Settings | None = None,
    engine: Engine | None = None,
    recognizer: Recognizer | None = None,
) -> FastAPI:
    settings = settings or Settings.from_env()
    log.setLevel(getattr(logging, settings.log_level, logging.INFO))
    engine = engine or make_engine()
    if settings.run_migrations:
        upgrade(engine)
    session_factory = make_session_factory(engine)
    store = EnrollmentStore(session_factory)
    recognizer = recognizer or build_recognizer(settings.recognizer_backend, settings.threshold)

    app = FastAPI(title="RESILIENCE face-id", version="1.0.0", docs_url=None, redoc_url=None)
    app.state.store = store
    app.state.recognizer = recognizer
    instrument(app, SERVICE_NAME)

    try:
        face_enrollments.set(store.count())
    except Exception as exc:  # noqa: BLE001 - la métrique ne doit jamais empêcher le démarrage
        log.debug("initialisation de la jauge d'enrôlements différée: %s", exc)

    def require_internal_token(x_internal_token: str = Header(default="")) -> None:
        # compare_digest exige des bytes pour tolérer un header non-ASCII (sinon TypeError -> 500).
        if not hmac.compare_digest(x_internal_token.encode(), settings.internal_token.encode()):
            raise HTTPException(status_code=401, detail="internal_token_invalid")

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
            log.warning("readiness DB check failed: %s", exc)  # détail seulement dans les logs
            problems.append("db injoignable")
        if problems:
            return JSONResponse(status_code=503, content={"status": "not_ready", "problems": problems})
        return {"status": "ready"}

    @app.post(
        "/api/v1/verify",
        response_model=VerifyResponse,
        dependencies=[Depends(require_internal_token)],
    )
    def verify(req: VerifyRequest) -> VerifyResponse:
        start = time.perf_counter()
        image = _decode_image(req.image_b64)
        try:
            probe = recognizer.embed(image)
        except NoFaceError as exc:
            face_verifications_total.labels("error").inc()
            log.warning(
                "Vérification impossible: aucun visage exploitable",
                extra={"event": "face_verify_error", "user": req.username},
            )
            raise HTTPException(status_code=422, detail="no_face_detected") from exc

        stored = store.get(req.username)
        if stored is not None and stored.model_version != recognizer.model_version:
            # Embedding enrôlé avec un AUTRE modèle : comparaison invalide. On le journalise
            # explicitement (réenrôlement requis) plutôt que de le confondre avec un vrai no-match.
            face_verifications_total.labels("error").inc()
            face_verify_duration_seconds.observe(time.perf_counter() - start)
            log.warning(
                "Embedding enrôlé avec un modèle différent (réenrôlement requis)",
                extra={"event": "face_verify_error", "user": req.username},
            )
            return VerifyResponse(match=False, model_version=recognizer.model_version)

        if stored is None:
            # Identifiant inconnu ou non enrôlé => non-correspondance
            # (anti-énumération : même réponse qu'un visage qui ne correspond pas).
            score, match = 0.0, False
        else:
            score = cosine_similarity(probe, deserialize_embedding(stored.embedding))
            match = score >= recognizer.threshold

        face_verify_duration_seconds.observe(time.perf_counter() - start)
        if match:
            face_verifications_total.labels("match").inc()
            # Le score reste côté serveur (logs), jamais renvoyé au client (anti hill-climbing).
            log.info(
                "Visage reconnu",
                extra={"event": "face_verify_match", "user": req.username, "score": round(score, 4)},
            )
        else:
            face_verifications_total.labels("nomatch").inc()
            log.info(
                "Visage non reconnu",
                extra={"event": "face_verify_nomatch", "user": req.username, "score": round(score, 4)},
            )
        return VerifyResponse(match=match, model_version=recognizer.model_version)

    @app.post(
        "/api/v1/enroll",
        response_model=EnrollResponse,
        dependencies=[Depends(require_internal_token)],
    )
    def enroll(req: EnrollRequest) -> EnrollResponse:
        embeddings: list[list[float]] = []
        for image_b64 in req.images_b64:
            image = _decode_image(image_b64)
            try:
                embeddings.append(recognizer.embed(image))
            except NoFaceError as exc:
                raise HTTPException(status_code=422, detail="no_face_detected") from exc
        # Qualité = cohérence inter-images (min des similarités au centroïde).
        centroid = _mean(embeddings)
        quality = min((cosine_similarity(e, centroid) for e in embeddings), default=1.0)
        try:
            store.upsert(
                req.username,
                serialize_embedding(centroid),
                recognizer.model_version,
                req.enrolled_by,
            )
        except UnknownUserError as exc:
            raise HTTPException(status_code=404, detail="unknown_user") from exc
        face_enrollments.set(store.count())
        log.info(
            "Visage enrôlé",
            extra={"event": "face_enrolled", "user": req.username},
        )
        return EnrollResponse(
            enrolled=True, quality=round(quality, 4), model_version=recognizer.model_version
        )

    @app.delete(
        "/api/v1/enroll/{username}",
        status_code=204,
        dependencies=[Depends(require_internal_token)],
    )
    def revoke(username: str):
        if not store.delete(username):
            raise HTTPException(status_code=404, detail="not_enrolled")
        face_enrollments.set(store.count())
        log.info(
            "Enrôlement révoqué",
            extra={"event": "face_enrollment_revoked", "user": username},
        )
        return Response(status_code=204)  # corps vide : un JSON null casse sous uvicorn (204)

    @app.get("/api/v1/enrollments", dependencies=[Depends(require_internal_token)])
    def enrollments() -> list[dict]:
        return store.list()

    return app
