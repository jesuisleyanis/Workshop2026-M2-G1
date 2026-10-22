"""Fixtures : SQLite en mémoire (suffisant en unitaire, cf. README), app isolée par test."""

import io
import json
import logging

import pytest
from fastapi.testclient import TestClient
from paykit import JWT_SECRET, WAF_IP, WAF_PEER, bearer, make_token
from resilience_db import Account, Base, User, make_engine, make_session_factory

from payment_api.config import SERVICE_NAME, Settings
from payment_api.main import create_app


@pytest.fixture
def settings():
    return Settings(jwt_secret=JWT_SECRET, run_migrations=False, trusted_proxies=(WAF_IP,))


@pytest.fixture
def engine():
    engine = make_engine("sqlite://")
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def db(engine):
    with make_session_factory(engine)() as session:
        yield session


@pytest.fixture
def world(db):
    """alice (compte 1: 100,00 EUR, compte 2: 5,00 EUR), bob (compte 3: 50,00 EUR)."""
    alice = User(username="alice", password_hash="x")
    bob = User(username="bob", password_hash="x")
    alice.accounts += [
        Account(iban_fake="FR76 A1", balance_cents=10_000, currency="EUR"),
        Account(iban_fake="FR76 A2", balance_cents=500, currency="EUR"),
    ]
    bob.accounts += [Account(iban_fake="FR76 B1", balance_cents=5_000, currency="EUR")]
    db.add_all([alice, bob])
    db.commit()
    return {"alice": alice, "bob": bob}


@pytest.fixture
def app(settings, engine, world):
    return create_app(settings, engine)


@pytest.fixture
def client(app):
    return TestClient(app)


@pytest.fixture
def waf_client(app):
    """Requêtes relayées par le WAF (pair de confiance) : leur X-Forwarded-For est cru."""
    return TestClient(app, client=WAF_PEER)


@pytest.fixture
def alice(world):
    return bearer(make_token("alice"))


@pytest.fixture
def log_lines():
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
