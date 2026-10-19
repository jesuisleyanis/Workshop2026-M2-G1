"""Intégration PostgreSQL réel (optionnelle) : migrations + verrous de ligne sous concurrence.

Ignoré par défaut (les tests unitaires utilisent SQLite). Pour l'activer :
    TEST_POSTGRES_URL=postgresql+psycopg://resilience:***@127.0.0.1:5432/resilience pytest -k postgres
La base ciblée doit être JETABLE : le test y crée des comptes fictifs.
"""

import os
import threading
import uuid

import pytest
from fastapi.testclient import TestClient
from paykit import JWT_SECRET, bearer, make_token
from resilience_db import Account, User, make_engine, make_session_factory

from payment_api.config import Settings
from payment_api.main import create_app

PG_URL = os.environ.get("TEST_POSTGRES_URL")
pytestmark = pytest.mark.skipif(not PG_URL, reason="TEST_POSTGRES_URL non défini")


def test_concurrent_transfers_never_overdraw_on_postgres():
    engine = make_engine(PG_URL)
    suffix = uuid.uuid4().hex[:8]
    username = f"it_{suffix}"
    with TestClient(
        create_app(Settings(jwt_secret=JWT_SECRET, run_migrations=True), engine)
    ) as client:
        with make_session_factory(engine)() as s:
            user = User(username=username, password_hash="x")
            user.accounts.append(
                Account(iban_fake=f"FR76 IT{suffix}A", balance_cents=100_000, currency="EUR")
            )
            peer = User(username=f"peer_{suffix}", password_hash="x")
            peer.accounts.append(
                Account(iban_fake=f"FR76 IT{suffix}B", balance_cents=0, currency="EUR")
            )
            s.add_all([user, peer])
            s.commit()
            src, dst = user.accounts[0].id, peer.accounts[0].id

        statuses: list[int] = []

        def pay():
            r = client.post(
                "/api/v1/transactions",
                headers=bearer(make_token(username)),
                json={"src_account": src, "dst_account": dst, "amount_cents": 30_000},
            )
            statuses.append(r.status_code)

        threads = [threading.Thread(target=pay) for _ in range(6)]
        [t.start() for t in threads]
        [t.join() for t in threads]

        assert sorted(statuses) == [201, 201, 201, 409, 409, 409]  # 3 x 300 EUR sur 1000 EUR
        with make_session_factory(engine)() as s:
            assert s.get(Account, src).balance_cents == 10_000
            assert s.get(Account, dst).balance_cents == 90_000
