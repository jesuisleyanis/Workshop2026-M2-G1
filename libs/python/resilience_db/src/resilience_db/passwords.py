"""Hash de mots de passe bcrypt (passlib). Partagé par le service auth et le seed."""

from __future__ import annotations

from passlib.context import CryptContext

_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto", bcrypt__rounds=12)

# bcrypt ne considère que les 72 premiers octets : on refuse plus long plutôt que de tronquer.
MAX_PASSWORD_BYTES = 72


def hash_password(password: str) -> str:
    if len(password.encode("utf-8")) > MAX_PASSWORD_BYTES:
        raise ValueError("password too long (max 72 bytes)")
    return _ctx.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    if len(password.encode("utf-8")) > MAX_PASSWORD_BYTES:
        return False
    return _ctx.verify(password, password_hash)


# Hash factice pour égaliser le temps de réponse quand l'utilisateur n'existe pas
# (évite l'énumération de comptes par timing).
DUMMY_HASH = _ctx.hash("not-a-real-password")
