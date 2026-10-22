"""Configuration du service face-id (variables d'environnement / secrets SOPS)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from face_id import SERVICE_NAME
from face_id.crypto import Sealer

_MIN_TOKEN_LEN = 16


def _read_secret(name: str) -> str | None:
    """Lit un secret depuis NAME_FILE (secret monté) en priorité, sinon NAME."""
    file_var = os.getenv(f"{name}_FILE")
    if file_var and Path(file_var).is_file():
        return Path(file_var).read_text().strip() or None
    return os.getenv(name) or None


@dataclass(frozen=True)
class Settings:
    """Paramètres du service. `from_env` échoue bruyamment si un secret requis manque."""

    internal_token: str
    #: Clé AES-256 (base64 de 32 octets) qui scelle gabarits et photos au repos.
    face_data_key: str
    recognizer_backend: str = "stub"
    threshold: float | None = None  # None => seuil par défaut du recognizer
    log_level: str = "INFO"
    run_migrations: bool = True

    @classmethod
    def from_env(cls) -> Settings:
        token = _read_secret("FACE_INTERNAL_TOKEN")
        if not token or len(token) < _MIN_TOKEN_LEN:
            raise RuntimeError(
                f"{SERVICE_NAME}: FACE_INTERNAL_TOKEN requis (>= {_MIN_TOKEN_LEN} caractères)."
            )
        data_key = _read_secret("FACE_DATA_KEY")
        if not data_key:
            raise RuntimeError(
                f"{SERVICE_NAME}: FACE_DATA_KEY requis (base64 de 32 octets, clé AES-256)."
            )
        try:
            Sealer.from_b64(data_key)  # validation seule : la clé n'est jamais loguée
        except ValueError as exc:
            raise RuntimeError(
                f"{SERVICE_NAME}: FACE_DATA_KEY invalide (base64 de 32 octets attendu)."
            ) from exc
        threshold = os.getenv("FACE_MATCH_THRESHOLD")
        return cls(
            internal_token=token,
            face_data_key=data_key,
            recognizer_backend=os.getenv("RECOGNIZER_BACKEND", "stub"),
            threshold=float(threshold) if threshold else None,
            log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
            run_migrations=os.getenv("RUN_MIGRATIONS", "1") not in {"0", "false", "False"},
        )
