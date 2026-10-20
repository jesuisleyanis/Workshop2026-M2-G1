"""Fixtures face-id : SQLite en mémoire, recognizer stub déterministe, app isolée par test."""

from __future__ import annotations

import base64
import io
import json
import logging

import pytest
from face_id import SERVICE_NAME
from face_id.config import Settings
from face_id.main import create_app
from face_id.recognizer import StubRecognizer
from fastapi.testclient import TestClient
from resilience_db import Base, make_engine, make_session_factory
from resilience_db.models import User

TOKEN = "face-internal-token-123456"
AUTH_HEADER = {"X-Internal-Token": TOKEN}


def b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode()


@pytest.fixture
def settings():
    return Settings(internal_token=TOKEN, recognizer_backend="stub", run_migrations=False)


@pytest.fixture
def engine():
    engine = make_engine("sqlite://")
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def session_factory(engine):
    return make_session_factory(engine)


@pytest.fixture
def seed_user(session_factory):
    """Un opérateur 'alice' existant (sans enrôlement)."""
    with session_factory() as s:
        s.add(User(username="alice", password_hash="x", role="operator"))
        s.commit()
    return "alice"


@pytest.fixture
def app(settings, engine):
    return create_app(settings, engine, recognizer=StubRecognizer())


@pytest.fixture
def client(app):
    return TestClient(app)


@pytest.fixture
def log_lines():
    logger = logging.getLogger(SERVICE_NAME)
    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    if logger.handlers:
        handler.setFormatter(logger.handlers[0].formatter)
    logger.addHandler(handler)

    def read(event: str | None = None) -> list[dict]:
        rows = [json.loads(line) for line in buf.getvalue().splitlines() if line.strip()]
        return [r for r in rows if event is None or r["event"] == event]

    yield read
    logger.removeHandler(handler)
