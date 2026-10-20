"""Schémas d'entrée/sortie de l'API auth."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator
from resilience_db.passwords import MAX_PASSWORD_BYTES


class RegisterRequest(BaseModel):
    username: str = Field(pattern=r"^[A-Za-z0-9_.-]{3,32}$")
    password: str = Field(min_length=8)

    @field_validator("password")
    @classmethod
    def _bcrypt_limit(cls, v: str) -> str:
        if len(v.encode("utf-8")) > MAX_PASSWORD_BYTES:
            raise ValueError("password too long (max 72 bytes)")
        return v


class LoginRequest(BaseModel):
    # Volontairement permissif : ne révèle pas les règles de format des comptes.
    username: str = Field(min_length=1, max_length=64)
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


class FaceRequest(BaseModel):
    challenge_id: str = Field(min_length=1, max_length=64)
    # Plafond anti-DoS (~1 Mo d'image en base64) : une trame webcam JPEG est bien en deçà.
    image_b64: str = Field(min_length=1, max_length=1_500_000)


class FaceResponse(BaseModel):
    recognized: bool
    step: str
    attempts_left: int


class PasswordRequest(BaseModel):
    challenge_id: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class SteppedTokenOut(TokenOut):
    role: str


class TightenRequest(BaseModel):
    factor: float = Field(gt=0, le=1, description="Multiplicateur de la limite courante.")


class RateLimitOut(BaseModel):
    previous_limit: str
    current_limit: str
