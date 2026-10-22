"""Fixtures : SQLite en mémoire (suffisant en unitaire, cf. README), app isolée par test."""

import io
import json
import logging

import pytest
from authkit import INTERNAL_TOKEN, JWT_SECRET, PASSWORD, WAF_IP, WAF_PEER
from fastapi.testclient import TestClient
from resilience_db import Base, make_engine, make_session_factory

from auth_service.config import SERVICE_NAME, Settings
from auth_service.main import create_app


@pytest.fixture
def settings():
    return Settings(
        jwt_secret=JWT_SECRET,
        internal_token=INTERNAL_TOKEN,
        login_rate_limit="3/minute",
        run_migrations=False,
        trusted_proxies=(WAF_IP,),
    )


@pytest.fixture
def engine():
    engine = make_engine("sqlite://")
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def app(settings, engine):
    return create_app(settings, engine)


@pytest.fixture
def client(app):
    return TestClient(app)


@pytest.fixture
def waf_client(app):
    """Requêtes relayées par le WAF (pair de confiance) : leur X-Forwarded-For est cru."""
    return TestClient(app, client=WAF_PEER)


@pytest.fixture
def db(engine):
    with make_session_factory(engine)() as session:
        yield session


@pytest.fixture
def registered(client):
    """Un utilisateur 'alice' créé via l'API."""
    r = client.post("/api/v1/register", json={"username": "alice", "password": PASSWORD})
    assert r.status_code == 201
    return "alice"


@pytest.fixture
def log_lines():
    """Capture les lignes JSON émises par le vrai logger du service (vrai formatter)."""
    logger = logging.getLogger(SERVICE_NAME)
    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    handler.setFormatter(logger.handlers[0].formatter)
    logger.addHandler(handler)

    def read(event: str | None = None) -> list[dict]:
        rows = [json.loads(line) for line in buf.getvalue().splitlines() if line]
        return [r for r in rows if event is None or r["event"] == event]

    yield read
    logger.removeHandler(handler)
