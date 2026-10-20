"""JWT HS256 (contrat REST : durée 15 min, claim sub = username)."""

from __future__ import annotations

import hmac
from datetime import UTC, datetime, timedelta

import jwt

ALGORITHM = "HS256"
TOKEN_TTL = timedelta(minutes=15)


def create_access_token(
    username: str, secret: str, now: datetime | None = None, role: str | None = None
) -> tuple[str, int]:
    """Renvoie (jwt, expires_in_seconds). `role` ajoute un claim `role` (back-office)."""
    now = now or datetime.now(UTC)
    payload = {"sub": username, "iat": now, "exp": now + TOKEN_TTL}
    if role is not None:
        payload["role"] = role
    return jwt.encode(payload, secret, algorithm=ALGORITHM), int(TOKEN_TTL.total_seconds())


def decode_access_token(token: str, secret: str) -> dict:
    """Décode et valide un JWT HS256 (signature, `exp`, présence de `sub`).

    Lève `jwt.InvalidTokenError` (dont `ExpiredSignatureError`) si le jeton est invalide.
    """
    return jwt.decode(
        token, secret, algorithms=[ALGORITHM], options={"require": ["exp", "sub"]}
    )


def internal_token_matches(provided: str | None, expected: str) -> bool:
    """Comparaison en temps constant du token interne."""
    return provided is not None and hmac.compare_digest(provided.encode(), expected.encode())
