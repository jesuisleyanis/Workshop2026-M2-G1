"""Configuration de connexion à la base (PostgreSQL en prod, SQLite en tests).

Aucun secret en dur : le mot de passe vient de POSTGRES_PASSWORD, ou du fichier
pointé par POSTGRES_PASSWORD_FILE (convention Docker/SOPS secrets).
"""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.engine import URL, make_url
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

DEFAULT_HOST = "postgres"
DEFAULT_PORT = 5432
DEFAULT_DB = "resilience"
DEFAULT_USER = "resilience"


def read_secret(name: str, *, required: bool = True) -> str | None:
    """Lit un secret depuis `NAME` ou, à défaut, depuis le fichier `NAME_FILE`."""
    value = os.environ.get(name)
    if value:
        return value
    file_path = os.environ.get(f"{name}_FILE")
    if file_path:
        return Path(file_path).read_text(encoding="utf-8").strip()
    if required:
        raise RuntimeError(f"Secret manquant : définir {name} ou {name}_FILE")
    return None


def build_database_url() -> URL:
    """Construit l'URL SQLAlchemy.

    `DATABASE_URL` (utilisée par les tests : sqlite) l'emporte ; sinon PostgreSQL
    `postgres:5432/resilience` avec l'utilisateur `resilience`.
    """
    explicit = os.environ.get("DATABASE_URL")
    if explicit:
        return make_url(explicit)
    return URL.create(
        "postgresql+psycopg",
        username=os.environ.get("POSTGRES_USER", DEFAULT_USER),
        password=read_secret("POSTGRES_PASSWORD"),
        host=os.environ.get("POSTGRES_HOST", DEFAULT_HOST),
        port=int(os.environ.get("POSTGRES_PORT", DEFAULT_PORT)),
        database=os.environ.get("POSTGRES_DB", DEFAULT_DB),
    )


def make_engine(url: URL | str | None = None) -> Engine:
    """Crée l'engine. SQLite (tests) : connexion unique partagée entre threads, FK actives."""
    url = make_url(url) if isinstance(url, str) else (url or build_database_url())
    if url.get_backend_name() == "sqlite":
        kwargs: dict = {"connect_args": {"check_same_thread": False}}
        if url.database in (None, "", ":memory:"):
            kwargs["poolclass"] = (
                StaticPool  # une seule base en mémoire pour tous les threads
            )
        engine = create_engine(url, **kwargs)

        @event.listens_for(engine, "connect")
        def _fk_on(dbapi_conn, _record):  # pragma: no cover - trivial
            dbapi_conn.execute("PRAGMA foreign_keys=ON")

        return engine
    return create_engine(
        url, pool_pre_ping=True, pool_size=5, max_overflow=5, pool_timeout=5
    )


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)
