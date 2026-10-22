"""Accès au stockage des enrôlements biométriques (table face_enrollments).

RGPD : le store ne manipule que des blobs DÉJÀ scellés (AES-GCM, cf. `crypto.py`) : gabarits
par pose et vignettes d'enrôlement. Le chiffrement/déchiffrement se fait dans la couche
service, jamais ici. La liste des enrôlements ne renvoie aucune donnée biométrique.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from resilience_db.models import FaceEnrollment, User
from sqlalchemy import func, select
from sqlalchemy.orm import Session


class UnknownUserError(LookupError):
    """L'identifiant n'existe pas (enrôlement d'un utilisateur inconnu refusé)."""


@dataclass(frozen=True)
class StoredEnrollment:
    templates_blob: bytes
    photos_blob: bytes | None  # NULL pour une ligne v1 (avant les photos chiffrées)
    model_version: str


class EnrollmentStore:
    def __init__(self, session_factory) -> None:
        self._session_factory = session_factory

    def _user_id(self, session: Session, username: str) -> int | None:
        return session.scalar(select(User.id).where(User.username == username))

    def user_exists(self, username: str) -> bool:
        with self._session_factory() as s:
            return self._user_id(s, username) is not None

    def get(self, username: str) -> StoredEnrollment | None:
        with self._session_factory() as s:
            row = s.execute(
                select(
                    FaceEnrollment.embedding,
                    FaceEnrollment.photos,
                    FaceEnrollment.model_version,
                )
                .join(User, User.id == FaceEnrollment.user_id)
                .where(User.username == username)
            ).first()
            return StoredEnrollment(row[0], row[1], row[2]) if row else None

    def upsert(
        self,
        username: str,
        templates_blob: bytes,
        photos_blob: bytes | None,
        poses_csv: str,
        model_version: str,
        enrolled_by: str,
    ) -> None:
        with self._session_factory() as s:
            user_id = self._user_id(s, username)
            if user_id is None:
                raise UnknownUserError(username)
            existing = s.scalar(
                select(FaceEnrollment).where(FaceEnrollment.user_id == user_id)
            )
            if existing is None:
                s.add(
                    FaceEnrollment(
                        user_id=user_id,
                        embedding=templates_blob,
                        photos=photos_blob,
                        poses=poses_csv,
                        model_version=model_version,
                        enrolled_by=enrolled_by,
                    )
                )
            else:
                existing.embedding = templates_blob
                existing.photos = photos_blob
                existing.poses = poses_csv
                existing.model_version = model_version
                existing.enrolled_by = enrolled_by
                existing.enrolled_at = datetime.now(UTC)
            s.commit()

    def delete(self, username: str) -> bool:
        with self._session_factory() as s:
            enr = s.scalar(
                select(FaceEnrollment)
                .join(User, User.id == FaceEnrollment.user_id)
                .where(User.username == username)
            )
            if enr is None:
                return False
            s.delete(enr)
            s.commit()
            return True

    def list(self, current_model_version: str) -> list[dict]:
        """Métadonnées d'enrôlement — jamais de gabarit ni de photo.

        `usable` : la ligne est vérifiable par le modèle chargé (`model_version` identique ET
        vignettes chiffrées présentes, donc format v2). Sinon (changement de modèle, ligne v1),
        toute vérification échoue : la ligne existe mais un réenrôlement est requis.
        """
        with self._session_factory() as s:
            rows = s.execute(
                select(
                    User.username,
                    FaceEnrollment.enrolled_at,
                    FaceEnrollment.enrolled_by,
                    FaceEnrollment.model_version,
                    FaceEnrollment.poses,
                    FaceEnrollment.photos.is_not(None),  # présence seule : le blob n'est pas lu
                ).join(User, User.id == FaceEnrollment.user_id)
            ).all()
            return [
                {
                    "username": u,
                    "enrolled_at": at.isoformat() if at else None,
                    "enrolled_by": by,
                    "model_version": mv,
                    "poses": [p for p in poses.split(",") if p],
                    "usable": bool(has_photos) and mv == current_model_version,
                }
                for (u, at, by, mv, poses, has_photos) in rows
            ]

    def count(self) -> int:
        with self._session_factory() as s:
            return int(s.scalar(select(func.count(FaceEnrollment.id))) or 0)
