"""Configuration du service auth, lue depuis l'environnement (aucun secret en dur)."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

from resilience_db.config import read_secret

SERVICE_NAME = "auth"
MIN_SECRET_LENGTH = 32
_RATE_RE = re.compile(r"^(\d+)/(second|minute|hour|day)$")


def _bool(name: str, default: bool) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in {"1", "true", "yes"}


@dataclass(frozen=True)
class Settings:
    jwt_secret: str
    internal_token: str
    login_rate_limit: str = "10/minute"
    trusted_proxy_hops: int = 1
    run_migrations: bool = True
    enable_docs: bool = False
    register_initial_balance_cents: int = 0
    log_level: str = "INFO"

    def __post_init__(self) -> None:
        if len(self.jwt_secret) < MIN_SECRET_LENGTH:
            raise RuntimeError(f"JWT_SECRET trop court (min {MIN_SECRET_LENGTH} caractères)")
        if len(self.internal_token) < 16:
            raise RuntimeError("INTERNAL_TOKEN trop court (min 16 caractères)")
        if not _RATE_RE.match(self.login_rate_limit):
            raise RuntimeError("LOGIN_RATE_LIMIT invalide (format attendu : '10/minute')")

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            jwt_secret=read_secret("JWT_SECRET"),
            internal_token=read_secret("INTERNAL_TOKEN"),
            login_rate_limit=os.environ.get("LOGIN_RATE_LIMIT", "10/minute"),
            trusted_proxy_hops=int(os.environ.get("TRUSTED_PROXY_HOPS", "1")),
            run_migrations=_bool("RUN_MIGRATIONS", True),
            enable_docs=_bool("ENABLE_DOCS", False),
            register_initial_balance_cents=int(
                os.environ.get("REGISTER_INITIAL_BALANCE_CENTS", "0")
            ),
            log_level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        )
