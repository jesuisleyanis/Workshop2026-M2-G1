"""Validation des JWT émis par le service auth (HS256, secret partagé JWT_SECRET)."""

from __future__ import annotations

import jwt

from payment_api.observability import ApiError

ALGORITHM = "HS256"


def username_from_token(token: str, secret: str) -> str:
    """Renvoie le claim `sub` d'un JWT valide, sinon lève ApiError(401).

    L'algorithme est ÉPINGLÉ à HS256 (rejette `alg: none` et la confusion d'algorithme),
    `exp` et `sub` sont obligatoires.
    """
    try:
        claims = jwt.decode(
            token, secret, algorithms=[ALGORITHM], options={"require": ["exp", "sub"]}
        )
    except jwt.ExpiredSignatureError:
        raise ApiError(401, "token_expired", "Token expired", _bearer("invalid_token"))
    except jwt.InvalidTokenError:
        raise ApiError(401, "invalid_token", "Invalid token", _bearer("invalid_token"))
    sub = claims["sub"]
    if not isinstance(sub, str) or not sub:
        raise ApiError(401, "invalid_token", "Invalid token", _bearer("invalid_token"))
    return sub


def _bearer(error: str | None = None) -> dict:
    return {"WWW-Authenticate": "Bearer" + (f' error="{error}"' if error else "")}


def missing_token() -> ApiError:
    return ApiError(401, "missing_token", "Authentication required", _bearer())
