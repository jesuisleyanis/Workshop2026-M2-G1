"""Schémas d'entrée/sortie de l'API auth."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator
from resilience_db.passwords import MAX_PASSWORD_BYTES


def _check_bcrypt_limit(v: str) -> str:
    if len(v.encode("utf-8")) > MAX_PASSWORD_BYTES:
        raise ValueError("password too long (max 72 bytes)")
    return v


class RegisterRequest(BaseModel):
    username: str = Field(pattern=r"^[A-Za-z0-9_.-]{3,32}$")
    password: str = Field(min_length=8)

    password_limit = field_validator("password")(_check_bcrypt_limit)


class LoginRequest(BaseModel):
    # Volontairement permissif : ne révèle pas les règles de format des comptes. Seuls les caractères
    # de contrôle (NUL…) sont refusés : psycopg les rejette en DataError (faux 503 db_error).
    username: str = Field(min_length=1, max_length=64, pattern=r"^[^\x00-\x1f\x7f]+$")
    password: str = Field(min_length=1, max_length=256)


class StepUpRequest(BaseModel):
    """Ré-authentification d'une session existante avant un gros virement (#51)."""

    password: str = Field(min_length=1, max_length=256)


class UserOut(BaseModel):
    id: int
    username: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


# --- Authentification à étapes du back-office (consigne additionnelle 1, contrat §5.2) ---


class IdentifyRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)


class IdentifyResponse(BaseModel):
    challenge_id: str
    step: str
    expires_in: int
    camera: bool
    #: Ordre des 3 poses à présenter (vide si le facteur visage est désactivé).
    poses: list[str]


class FaceFrame(BaseModel):
    pose: Literal["face", "gauche", "droite"]
    # Plafond anti-DoS (~600 Ko d'image) : une trame webcam JPEG est bien en deçà.
    image_b64: str = Field(min_length=1, max_length=800_000)


class FaceRequest(BaseModel):
    challenge_id: str = Field(min_length=1, max_length=64)
    # Exactement une frame par pose demandée, dans l'ordre tiré par identify.
    frames: list[FaceFrame] = Field(min_length=3, max_length=3)


class FaceResponse(BaseModel):
    recognized: bool
    step: str
    attempts_left: int
    #: Secondes de refroidissement imposées (30 si non reconnu, sinon 0).
    cooldown: int = 0


class PasswordRequest(BaseModel):
    challenge_id: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class SteppedTokenOut(TokenOut):
    role: str


# --- API d'administration des habilitations + bootstrap (T5) ---

Role = Literal["customer", "operator", "admin"]
# Plafond anti-DoS par photo (cf. FaceFrame) : une capture webcam JPEG est bien en deçà.
_PHOTO = Field(min_length=1, max_length=800_000)


class AdminUserCreate(BaseModel):
    username: str = Field(pattern=r"^[A-Za-z0-9_.-]{3,32}$")
    password: str = Field(min_length=8)
    role: Role

    password_limit = field_validator("password")(_check_bcrypt_limit)


class RoleUpdate(BaseModel):
    role: Role


class EnrollPoses(BaseModel):
    """Exactement les 3 poses d'enrôlement (clés figées du contrat), images en base64."""

    model_config = {"extra": "forbid"}

    face: str = _PHOTO
    gauche: str = _PHOTO
    droite: str = _PHOTO


class EnrollRequest(BaseModel):
    poses: EnrollPoses


class AdminUserOut(BaseModel):
    username: str
    role: Role


class AdminUserRow(AdminUserOut):
    enrolled: bool  # enrôlement UTILISABLE (vérifiable par le modèle chargé de face-id)
    stale: bool = False  # ligne d'enrôlement présente mais périmée : réenrôlement requis
    enrolled_at: str | None = None
    enrolled_by: str | None = None


class EnrollOut(BaseModel):
    enrolled: bool = True
    model_version: str | None = None


class PhotosOut(BaseModel):
    photos: dict[str, str]


class BootstrapStatus(BaseModel):
    required: bool


class BootstrapRequest(BaseModel):
    token: str = Field(max_length=256)
    username: str = Field(pattern=r"^[A-Za-z0-9_.-]{3,32}$")
    password: str = Field(min_length=8)
    poses: EnrollPoses

    password_limit = field_validator("password")(_check_bcrypt_limit)


class TightenRequest(BaseModel):
    factor: float = Field(gt=0, le=1, description="Multiplicateur de la limite courante.")


class RateLimitOut(BaseModel):
    previous_limit: str
    current_limit: str
