"""Constantes et helpers partagés par les tests."""

from datetime import UTC, datetime, timedelta

import jwt
from prometheus_client import REGISTRY

JWT_SECRET = "test-secret-test-secret-test-secret-0123"


def sample(name: str, **labels) -> float:
    return REGISTRY.get_sample_value(name, labels) or 0.0


def make_token(sub="alice", secret=JWT_SECRET, ttl=timedelta(minutes=15), **overrides) -> str:
    now = datetime.now(UTC)
    # Comme un login réel : `auth_time` = maintenant (#51, step-up des gros virements).
    claims = {
        "sub": sub,
        "iat": now,
        "exp": now + ttl,
        "auth_time": int(now.timestamp()),
        **overrides,
    }
    claims = {k: v for k, v in claims.items() if v is not None}
    return jwt.encode(claims, secret, algorithm="HS256")


def bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}
