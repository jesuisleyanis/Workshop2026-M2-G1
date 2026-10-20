"""Accès au stockage des enrôlements biométriques (table face_enrollments).

RGPD : seul l'embedding (vecteur) est persisté, jamais l'image. La liste des enrôlements
ne renvoie aucune donnée biométrique.
"""

from __future__ import annotations

from dataclasses import dataclass

from resilience_db.models import FaceEnrollment, User
from sqlalchemy import func, select
from sqlalchemy.orm import Session


class UnknownUserError(LookupError):
    """L'identifiant n'existe pas (enrôlement d'un utilisateur inconnu refusé)."""


@dataclass(frozen=True)
class StoredEmbedding:
    embedding: bytes
    model_version: str


class EnrollmentStore:
    def __init__(self, session_factory) -> None:
        self._session_factory = session_factory

    def _user_id(self, session: Session, username: str) -> int | None:
        return session.scalar(select(User.id).where(User.username == username))

    def get(self, username: str) -> StoredEmbedding | None:
        with self._session_factory() as s:
            row = s.execute(
                select(FaceEnrollment.embedding, FaceEnrollment.model_version)
                .join(User, User.id == FaceEnrollment.user_id)
                .where(User.username == username)
            ).first()
            return StoredEmbedding(row[0], row[1]) if row else None

    def upsert(
        self, username: str, embedding: bytes, model_version: str, enrolled_by: str
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
                        embedding=embedding,
                        model_version=model_version,
                        enrolled_by=enrolled_by,
                    )
                )
            else:
                existing.embedding = embedding
                existing.model_version = model_version
                existing.enrolled_by = enrolled_by
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

    def list(self) -> list[dict]:
        """Métadonnées d'enrôlement — jamais l'embedding."""
        with self._session_factory() as s:
            rows = s.execute(
                select(
                    User.username,
                    FaceEnrollment.enrolled_at,
                    FaceEnrollment.enrolled_by,
                    FaceEnrollment.model_version,
                ).join(User, User.id == FaceEnrollment.user_id)
            ).all()
            return [
                {
                    "username": u,
                    "enrolled_at": at.isoformat() if at else None,
                    "enrolled_by": by,
                    "model_version": mv,
                }
                for (u, at, by, mv) in rows
            ]

    def count(self) -> int:
        with self._session_factory() as s:
            return int(s.scalar(select(func.count(FaceEnrollment.id))) or 0)
