"""Configuration du service payment-api, lue depuis l'environnement (aucun secret en dur)."""

from __future__ import annotations

import os
from dataclasses import dataclass

from resilience_db.config import read_secret

SERVICE_NAME = "payment-api"
MIN_SECRET_LENGTH = 32
MIN_STATUS_CACHE_S, MAX_STATUS_CACHE_S = 0.5, 30.0


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
    # Exécuteur des virements programmés (#48) : tâche de fond, une passe par intervalle.
    scheduler_enabled: bool = True
    scheduler_interval_s: float = 60.0
    # Authentification renforcée (#51) : au-delà du seuil, mot de passe vérifié depuis moins
    # de STEP_UP_MAX_AGE_S (claim `auth_time` du JWT émis par auth). verify_tx (1 €) en dessous.
    step_up_threshold_cents: int = 50_000
    step_up_max_age_s: int = 300

    def __post_init__(self) -> None:
        if len(self.jwt_secret) < MIN_SECRET_LENGTH:
            raise RuntimeError(f"JWT_SECRET trop court (min {MIN_SECRET_LENGTH} caractères)")
        if self.step_up_threshold_cents < 0 or not 30 <= self.step_up_max_age_s <= 3600:
            raise RuntimeError("STEP_UP_THRESHOLD_CENTS >= 0 et STEP_UP_MAX_AGE_S dans [30, 3600]")
        # Sous MIN_STATUS_CACHE_S, la route publique /api/v1/status redevient amplificatrice.
        if not MIN_STATUS_CACHE_S <= self.status_cache_s <= MAX_STATUS_CACHE_S:
            raise RuntimeError(
                f"STATUS_CACHE_S hors bornes [{MIN_STATUS_CACHE_S}, {MAX_STATUS_CACHE_S}]"
            )

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            jwt_secret=read_secret("JWT_SECRET"),
            trusted_proxy_hops=int(os.environ.get("TRUSTED_PROXY_HOPS", "1")),
            run_migrations=_bool("RUN_MIGRATIONS", True),
            enable_docs=_bool("ENABLE_DOCS", False),
            log_level=os.environ.get("LOG_LEVEL", "INFO").upper(),
            status_cache_s=float(os.environ.get("STATUS_CACHE_S", "2")),
            scheduler_enabled=_bool("SCHEDULER_ENABLED", True),
            scheduler_interval_s=float(os.environ.get("SCHEDULER_INTERVAL_S", "60")),
            step_up_threshold_cents=int(os.environ.get("STEP_UP_THRESHOLD_CENTS", "50000")),
            step_up_max_age_s=int(os.environ.get("STEP_UP_MAX_AGE_S", "300")),
        )
