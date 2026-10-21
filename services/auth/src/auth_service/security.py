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
    """Renvoie (jwt, expires_in_seconds). `role` ajoute un claim `role` (back-office).

    `auth_time` (#51) = instant où le mot de passe vient d'être vérifié : un login ou une
    ré-authentification (step-up) récents autorisent les gros virements côté payment-api.
    """
    now = now or datetime.now(UTC)
    payload = {
        "sub": username,
        "iat": now,
        "exp": now + TOKEN_TTL,
        "auth_time": int(now.timestamp()),
    }
    if role is not None:
        payload["role"] = role
    return jwt.encode(payload, secret, algorithm=ALGORITHM), int(TOKEN_TTL.total_seconds())


def internal_token_matches(provided: str | None, expected: str) -> bool:
    """Comparaison en temps constant du token interne."""
    return provided is not None and hmac.compare_digest(provided.encode(), expected.encode())


def username_from_bearer(authorization: str | None, secret: str) -> str | None:
    """`sub` d'un JWT valide (HS256 épinglé, exp/sub obligatoires), sinon None."""
    if not authorization or not authorization.startswith("Bearer "):
        return None
    try:
        claims = jwt.decode(
            authorization[7:], secret, algorithms=[ALGORITHM], options={"require": ["exp", "sub"]}
        )
    except jwt.InvalidTokenError:
        return None
    sub = claims.get("sub")
    return sub if isinstance(sub, str) and sub else None
