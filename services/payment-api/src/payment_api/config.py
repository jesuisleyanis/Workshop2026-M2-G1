"""Configuration du service payment-api, lue depuis l'environnement (aucun secret en dur)."""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from resilience_db.config import read_secret

SERVICE_NAME = "payment-api"
MIN_SECRET_LENGTH = 32


def _bool(name: str, default: bool) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in {"1", "true", "yes"}


@dataclass(frozen=True)
class Settings:
    jwt_secret: str
    trusted_proxy_hops: int = 1
    run_migrations: bool = True
    enable_docs: bool = False
    log_level: str = "INFO"
    status_cache_s: float = 2.0
    clock: Callable[[], float] = field(default=time.monotonic, compare=False, repr=False)

    def __post_init__(self) -> None:
        if len(self.jwt_secret) < MIN_SECRET_LENGTH:
            raise RuntimeError(f"JWT_SECRET trop court (min {MIN_SECRET_LENGTH} caractères)")

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            jwt_secret=read_secret("JWT_SECRET"),
            trusted_proxy_hops=int(os.environ.get("TRUSTED_PROXY_HOPS", "1")),
            run_migrations=_bool("RUN_MIGRATIONS", True),
            enable_docs=_bool("ENABLE_DOCS", False),
            log_level=os.environ.get("LOG_LEVEL", "INFO").upper(),
            status_cache_s=float(os.environ.get("STATUS_CACHE_S", "2")),
        )
