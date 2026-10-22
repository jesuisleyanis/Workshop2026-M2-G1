"""API d'administration des habilitations du back-office + bootstrap du premier administrateur.

Réservée au rôle `admin` (JWT émis par l'authentification à étapes, `Authorization: Bearer`).
Le rôle du jeton est **revalidé en base** à chaque appel : un administrateur rétrogradé perd
l'accès immédiatement, sans attendre l'expiration de son jeton (15 min).

Règle `last_admin` : une opération qui retirerait le dernier administrateur **enrôlé** (rôle
rétrogradé ou gabarit révoqué) est refusée, sinon plus personne ne pourrait franchir l'étape
visage du back-office. « Enrôlé » se lit auprès de face-id et ne compte que les enrôlements
**utilisables** (`usable: true` : vérifiables par le modèle chargé) ; une ligne périmée (autre
modèle, ligne v1) ne permet pas de se connecter, elle ne compte donc pas. Si face-id est
injoignable, les routes qui en dépendent répondent 503 `face_service_unavailable` (jamais une
réponse par défaut).

Bootstrap : tant qu'aucun administrateur enrôlé n'existe ET qu'un `BACKOFFICE_BOOTSTRAP_TOKEN`
est configuré, ce token permet de créer le premier administrateur (compte + visage). L'opération
est atomique côté métier : si l'enrôlement échoue, la création est annulée.
"""

from __future__ import annotations

import hmac
import logging
import threading

import jwt
from fastapi import Depends, FastAPI, Header, Request, Response
from resilience_db.models import User
from resilience_db.passwords import hash_password
from slowapi import Limiter
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from auth_service.backoffice import find_user_ci
from auth_service.config import Settings
from auth_service.face_client import EnrollmentRejectedError, FaceIdClient, FaceUnavailable
from auth_service.observability import ApiError, log_event
from auth_service.schemas import (
    AdminUserCreate,
    AdminUserOut,
    AdminUserRow,
    BootstrapRequest,
    BootstrapStatus,
    EnrollOut,
    EnrollRequest,
    PhotosOut,
    RoleUpdate,
)
from auth_service.security import decode_access_token

BOOTSTRAP_RATE_LIMIT = "5/minute"


def add_admin_api(
    app: FastAPI,
    *,
    settings: Settings,
    session_factory,
    log: logging.Logger,
    face_client: FaceIdClient,
    limiter: Limiter,
) -> None:
    """Ajoute les routes `/api/v1/admin/*` et `/api/v1/auth/bootstrap`."""

    rate = settings.backoffice_rate_limit
    # Sérialise les opérations qui modifient l'ensemble des administrateurs enrôlés (garde
    # last_admin, bootstrap) : sans cela, deux rétrogradations concurrentes passeraient chacune
    # le contrôle. Portée : ce processus (un seul worker uvicorn dans la stack).
    admins_lock = threading.Lock()

    # ---------------------------------------------------------------- aides

    def _face(fn, *args):
        """Appelle face-id ; l'indisponibilité devient 503 (jamais de valeur par défaut)."""
        try:
            return fn(*args)
        except FaceUnavailable as exc:
            raise ApiError(503, "face_service_unavailable", "Face service unavailable") from exc

    def _usable(rows: list[dict]) -> set[str]:
        """Usernames dont l'enrôlement est vérifiable par le modèle chargé (`usable` strict)."""
        return {row["username"] for row in rows if row.get("usable") is True}

    def _enrolled_admins(session) -> set[str]:
        enrolled = _usable(_face(face_client.enrollments))
        admins = set(session.scalars(select(User.username).where(User.role == "admin")))
        return admins & enrolled

    def _canonical(username: str) -> str:
        """Nom canonique (casse stockée en base) d'un `{username}` de chemin ; le nom saisi tel
        quel s'il n'existe pas (les routes répondent alors 404 comme avant)."""
        with session_factory() as session:
            user = find_user_ci(session, username)
        return user.username if user is not None else username

    def _enroll(username: str, poses: dict[str, str], enrolled_by: str) -> dict:
        try:
            return face_client.enroll(username, poses, enrolled_by)
        except EnrollmentRejectedError as exc:
            raise ApiError(
                422, "enrollment_rejected", "Face enrollment rejected", details=exc.details
            ) from exc
        except LookupError as exc:
            raise ApiError(404, "unknown_user", "Unknown user") from exc
        except Exception as exc:  # FaceUnavailable, corps 200 illisible... : état inconnu
            raise ApiError(503, "face_service_unavailable", "Face service unavailable") from exc

    def require_admin(authorization: str | None = Header(default=None)) -> str:
        """Dépendance : renvoie le username de l'administrateur authentifié."""
        scheme, _, token = (authorization or "").partition(" ")
        if scheme.lower() != "bearer" or not token.strip():
            raise ApiError(401, "missing_token", "Missing bearer token")
        try:
            claims = decode_access_token(token.strip(), settings.jwt_secret)
        except jwt.InvalidTokenError as exc:
            raise ApiError(401, "invalid_token", "Invalid or expired token") from exc
        if claims.get("role") != "admin":
            raise ApiError(403, "forbidden", "Administrator role required")
        username = claims["sub"]
        with session_factory() as session:
            current = session.scalar(select(User.role).where(User.username == username))
        if current is None:
            raise ApiError(401, "invalid_token", "Invalid or expired token")
        if current != "admin":
            raise ApiError(403, "forbidden", "Administrator role required")
        return username

    # ---------------------------------------------------------------- comptes

    @app.get("/api/v1/admin/users", response_model=list[AdminUserRow])
    @limiter.limit(rate)
    def list_users(request: Request, actor: str = Depends(require_admin)):
        enrolled = {row["username"]: row for row in _face(face_client.enrollments)}
        with session_factory() as session:
            users = session.execute(select(User.username, User.role).order_by(User.username)).all()
        rows = []
        for username, role in users:
            info = enrolled.get(username)
            usable = info is not None and info.get("usable") is True
            rows.append(
                AdminUserRow(
                    username=username,
                    role=role,
                    enrolled=usable,
                    # Ligne présente mais inutilisable (changement de modèle, ligne v1) :
                    # le back-office affiche « Réenrôlement requis ».
                    stale=info is not None and not usable,
                    enrolled_at=info.get("enrolled_at") if info else None,
                    enrolled_by=info.get("enrolled_by") if info else None,
                )
            )
        return rows

    @app.post("/api/v1/admin/users", response_model=AdminUserOut, status_code=201)
    @limiter.limit(rate)
    def create_user(request: Request, body: AdminUserCreate, actor: str = Depends(require_admin)):
        password_hash = hash_password(body.password)
        with session_factory() as session:
            # Insensible à la casse : « louis » est pris si « Louis » existe (l'identifiant du
            # back-office est résolu sans tenir compte de la casse, cf. backoffice.py).
            if find_user_ci(session, body.username) is not None:
                raise ApiError(409, "username_taken", "Username already exists")
            # Compte du back-office : aucun compte bancaire n'est créé.
            session.add(User(username=body.username, password_hash=password_hash, role=body.role))
            try:
                session.commit()
            except IntegrityError:  # course : même username créé entre le SELECT et l'INSERT
                session.rollback()
                raise ApiError(409, "username_taken", "Username already exists")
        log_event(
            log,
            logging.INFO,
            "admin_user_created",
            f"Admin {actor} created user {body.username} with role {body.role}",
            http_status=201,
            user=body.username,
        )
        return AdminUserOut(username=body.username, role=body.role)

    @app.patch("/api/v1/admin/users/{username}", response_model=AdminUserOut)
    @limiter.limit(rate)
    def change_role(
        request: Request, username: str, body: RoleUpdate, actor: str = Depends(require_admin)
    ):
        with admins_lock, session_factory() as session:
            user = find_user_ci(session, username)
            if user is None:
                raise ApiError(404, "unknown_user", "Unknown user")
            username = user.username
            previous = user.role
            # Le face-id n'est interrogé que si la rétrogradation peut vider le groupe.
            if (
                previous == "admin"
                and body.role != "admin"
                and _enrolled_admins(session) == {username}
            ):
                raise ApiError(409, "last_admin", "Cannot remove the last enrolled admin")
            if previous != body.role:
                user.role = body.role
                session.commit()
                log_event(
                    log,
                    logging.INFO,
                    "admin_role_changed",
                    f"Admin {actor} changed role of {username}: {previous} -> {body.role}",
                    http_status=200,
                    user=username,
                )
            return AdminUserOut(username=username, role=body.role)

    # ---------------------------------------------------------------- visage

    @app.put("/api/v1/admin/users/{username}/face", response_model=EnrollOut)
    @limiter.limit(rate)
    def enroll_face(
        request: Request, username: str, body: EnrollRequest, actor: str = Depends(require_admin)
    ):
        with session_factory() as session:
            user = find_user_ci(session, username)
            if user is None:
                raise ApiError(404, "unknown_user", "Unknown user")
            username = user.username
        result = _enroll(username, body.poses.model_dump(), actor)
        log_event(
            log,
            logging.INFO,
            "admin_face_enrolled",
            f"Admin {actor} enrolled the face of {username}",
            http_status=200,
            user=username,
        )
        return EnrollOut(model_version=result.get("model_version"))

    @app.delete("/api/v1/admin/users/{username}/face", status_code=204)
    @limiter.limit(rate)
    def revoke_face(request: Request, username: str, actor: str = Depends(require_admin)):
        username = _canonical(username)
        with admins_lock:
            with session_factory() as session:
                role = session.scalar(select(User.role).where(User.username == username))
                if role == "admin" and _enrolled_admins(session) == {username}:
                    raise ApiError(409, "last_admin", "Cannot remove the last enrolled admin")
            if not _face(face_client.revoke, username):
                raise ApiError(404, "not_enrolled", "User has no face enrollment")
        log_event(
            log,
            logging.INFO,
            "admin_face_revoked",
            f"Admin {actor} revoked the face enrollment of {username}",
            http_status=204,
            user=username,
        )
        return Response(status_code=204)

    @app.get("/api/v1/admin/users/{username}/face/photos", response_model=PhotosOut)
    @limiter.limit(rate)
    def face_photos(request: Request, username: str, actor: str = Depends(require_admin)):
        # `actor` est transmis comme `viewer` : face-id journalise la consultation (face_photos_viewed).
        photos = _face(face_client.photos, _canonical(username), actor)
        if photos is None:
            raise ApiError(404, "not_enrolled", "User has no face enrollment")
        return PhotosOut(photos=photos)

    # ---------------------------------------------------------------- bootstrap

    def _bootstrap_state() -> tuple[bool, set[str]]:
        """(bootstrap requis ?, usernames ayant une ligne d'enrôlement chez face-id).

        Requis tant qu'aucun admin n'a d'enrôlement **utilisable** : des lignes périmées ne
        permettent à personne de franchir l'étape visage. Le second ensemble (toutes lignes,
        même périmées) sert au rollback : on ne révoque jamais un enrôlement préexistant.
        """
        if not settings.backoffice_bootstrap_token:
            return False, set()  # jamais requis : bootstrap désactivé
        rows = _face(face_client.enrollments)
        with session_factory() as session:
            admins = set(session.scalars(select(User.username).where(User.role == "admin")))
        return not (admins & _usable(rows)), {row["username"] for row in rows}

    def _bootstrap_required() -> bool:
        return _bootstrap_state()[0]

    @app.get("/api/v1/auth/bootstrap", response_model=BootstrapStatus)
    @limiter.limit(rate)
    def bootstrap_status(request: Request):
        return BootstrapStatus(required=_bootstrap_required())

    def _bootstrap_denied(username: str, reason: str) -> ApiError:
        log_event(
            log,
            logging.WARNING,
            "backoffice_bootstrap",
            f"Bootstrap denied for {username}: {reason}",
            http_status=403,
            user=username,
        )
        return ApiError(403, "bootstrap_denied", "Bootstrap denied")

    def _rollback_bootstrap(
        username: str, snapshot: tuple[str, str] | None, revoke_template: bool
    ) -> None:
        """Annule un bootstrap en échec, sans jamais masquer l'erreur d'origine.

        1. Révoque le gabarit si besoin : face-id a pu l'enregistrer alors qu'`auth` voit un
           échec (délai dépassé, 5xx après commit, corps illisible) ; sans cela la suppression
           du compte violerait la clé étrangère `face_enrollments.user_id`.
        2. Supprime le compte créé / restaure mot de passe + rôle du compte préexistant.
        Une panne ici est journalisée (ERROR) ; l'appelant relève l'erreur d'origine.
        """
        if revoke_template:
            try:
                face_client.revoke(username)
            except Exception:  # noqa: BLE001, S110 - meilleur effort, l'échec d'origine prime
                pass
        try:
            _undo_bootstrap_user(username, snapshot)
        except Exception as exc:  # noqa: BLE001
            log_event(
                log,
                logging.ERROR,
                "backoffice_bootstrap",
                f"Bootstrap rollback failed for {username} ({type(exc).__name__}): "
                "manual check of the account required",
                http_status=503,
                user=username,
            )

    def _undo_bootstrap_user(username: str, snapshot: tuple[str, str] | None) -> None:
        """Annule la création (ou restaure mot de passe + rôle d'un compte préexistant)."""
        with session_factory() as session:
            user = session.scalar(select(User).where(User.username == username))
            if user is None:
                return
            if snapshot is None:
                session.delete(user)
            else:
                user.password_hash, user.role = snapshot
            session.commit()

    @app.post("/api/v1/auth/bootstrap", response_model=AdminUserOut, status_code=201)
    @limiter.limit(BOOTSTRAP_RATE_LIMIT)
    def bootstrap(request: Request, body: BootstrapRequest):
        configured = settings.backoffice_bootstrap_token
        # Token vide = bootstrap désactivé : compare_digest("", "") serait vrai, on l'exclut.
        if not configured or not hmac.compare_digest(body.token.encode(), configured.encode()):
            raise _bootstrap_denied(body.username, "invalid or disabled token")
        password_hash = hash_password(body.password)
        with admins_lock:
            required, enrolled = _bootstrap_state()
            if not required:
                raise _bootstrap_denied(body.username, "an enrolled admin already exists")
            with session_factory() as session:
                # Insensible à la casse : « louis » désigne le compte existant « Louis » (même
                # règle de rôle) ; la suite utilise le nom canonique stocké en base.
                user = find_user_ci(session, body.username)
                username = user.username if user is not None else body.username
                snapshot: tuple[str, str] | None = None
                if user is not None and user.role not in ("admin", "operator"):
                    # Un compte client existant ne peut pas être promu par le bootstrap.
                    raise _bootstrap_denied(username, "existing account is not staff")
                if user is None:
                    # Premier administrateur : aucun compte bancaire.
                    session.add(User(username=username, password_hash=password_hash, role="admin"))
                else:
                    snapshot = (user.password_hash, user.role)
                    user.password_hash, user.role = password_hash, "admin"
                session.commit()
            try:
                # face-id lit le compte en base : l'enrôlement ne peut avoir lieu qu'après commit.
                _enroll(username, body.poses.model_dump(), username)
            except ApiError as exc:
                # 422/404 : face-id a refusé, rien n'est stocké. Autre échec (503) : état
                # incertain, on révoque, sauf si le compte était déjà enrôlé avant le bootstrap
                # (on ne détruit pas un enrôlement légitime).
                uncertain = exc.status not in (404, 422)
                _rollback_bootstrap(username, snapshot, uncertain and username not in enrolled)
                raise
        log_event(
            log,
            logging.INFO,
            "backoffice_bootstrap",
            f"Bootstrap token holder created the first admin {username} (face enrolled)",
            http_status=201,
            user=username,
        )
        return AdminUserOut(username=username, role="admin")
