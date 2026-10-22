"""Plafond mensuel de virement (#46) : contrôle au ledger + GET /api/v1/limits."""

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from paykit import JWT_SECRET, sample
from resilience_db.models import Account, Transaction

from payment_api.config import Settings
from payment_api.main import create_app

TX = "/api/v1/transactions"
LIM = "/api/v1/limits"


class Clock:
    def __init__(self, at: datetime) -> None:
        self.at = at

    def __call__(self) -> datetime:
        return self.at


@pytest.fixture
def clock():
    return Clock(datetime(2026, 10, 21, 12, 0, tzinfo=UTC))


@pytest.fixture
def alice(world, clock):
    """Jeton dont `auth_time` suit l'horloge injectée (step-up #51 évalué à cette heure-là)."""
    from paykit import bearer, make_token

    return bearer(make_token("alice", auth_time=int(clock().timestamp())))


@pytest.fixture
def capped(engine, world, db, clock):
    """alice : compte 1 plafonné à 50,00 € ; compte 2 sans plafond. Horloge injectée."""
    acc = db.get(Account, 1)
    acc.monthly_limit_cents = 5_000
    db.commit()
    settings = Settings(jwt_secret=JWT_SECRET, run_migrations=False)
    return TestClient(create_app(settings, engine, now=clock))


def _send(client, headers, amount, src=1, dst=3):
    return client.post(
        TX, headers=headers, json={"src_account": src, "dst_account": dst, "amount_cents": amount}
    )


def test_under_the_limit_ok_then_exceeding_is_409_traced(capped, alice, db, log_lines):
    assert _send(capped, alice, 3_000).status_code == 201
    assert _send(capped, alice, 2_000).status_code == 201, "pile au plafond : accepté"
    before = sample("resilience_transactions_total", result="rejected")
    r = _send(capped, alice, 1)
    assert r.status_code == 409 and r.json()["error"]["code"] == "limit_exceeded"
    assert sample("resilience_transactions_total", result="rejected") == before + 1
    (e,) = log_lines("transaction_rejected")
    assert "limit_exceeded" in e["message"] and e["http_status"] == 409
    rejected = db.query(Transaction).filter_by(status="rejected").one()
    assert rejected.amount_cents == 1, "refus persisté et traçable (R2)"
    db.expire_all()
    assert db.get(Account, 1).balance_cents == 10_000 - 5_000, "solde intact sur refus"


def test_limit_resets_at_month_change(capped, alice, clock, db):
    # Dépense datée explicitement (pas l'horloge murale) : le test ne dépend pas du jour réel.
    db.add(
        Transaction(
            src_account=1, dst_account=3, amount_cents=5_000, status="created", created_at=clock.at
        )
    )
    db.commit()
    assert _send(capped, alice, 1).status_code == 409
    clock.at = datetime(2026, 11, 1, 0, 0, tzinfo=UTC)
    assert _send(capped, alice, 1).status_code == 201, "nouveau mois : plafond remis à zéro"


def test_future_dated_rows_do_not_count_in_a_past_window(capped, alice, db, clock):
    db.add(
        Transaction(
            src_account=1,
            dst_account=3,
            amount_cents=5_000,
            status="created",
            created_at=datetime(2026, 11, 3, tzinfo=UTC),
        )
    )
    db.commit()
    assert _send(capped, alice, 5_000).status_code == 201, "fenêtre bornée à [1er, 1er suivant)"


def test_internal_transfers_and_uncapped_accounts_are_not_limited(capped, alice):
    assert _send(capped, alice, 6_000, src=1, dst=2).status_code == 201, "entre mes comptes"
    assert _send(capped, alice, 500, src=2, dst=3).status_code == 201, "compte sans plafond"
    assert _send(capped, alice, 4_000).status_code == 201, "l'interne n'a rien consommé"


def test_rejected_transfers_do_not_consume_the_limit(capped, alice):
    assert _send(capped, alice, 999_999).status_code in (409, 422)
    assert _send(capped, alice, 5_000).status_code == 201


def test_get_limits_reports_used_remaining_and_reset_date(capped, alice):
    _send(capped, alice, 1_200)
    _send(capped, alice, 700, src=1, dst=2)  # interne : non compté
    body = capped.get(LIM, headers=alice).json()
    assert body == [
        {
            "account_id": 1,
            "monthly_limit_cents": 5_000,
            "used_cents": 1_200,
            "remaining_cents": 3_800,
            "period_end": "2026-11-01",
        },
        {
            "account_id": 2,
            "monthly_limit_cents": None,
            "used_cents": 0,
            "remaining_cents": None,
            "period_end": "2026-11-01",
        },
    ]


def test_limits_are_scoped_to_the_caller_and_require_a_bearer(capped):
    from paykit import bearer, make_token

    body = capped.get(LIM, headers=bearer(make_token("bob"))).json()
    assert [row["account_id"] for row in body] == [3]
    assert capped.get(LIM).status_code == 401


def test_verify_tx_service_account_is_never_capped_even_after_heavy_traffic(engine, db, clock):
    """La vérification de démo (demo01 -> demo02) ne peut jamais échouer sur le plafond."""
    from paykit import bearer, make_token
    from resilience_db.seed import seed_demo_data

    seed_demo_data(db, "s3cret-pass", users=2)
    src = db.query(Account).filter_by(iban_fake="FR76 0000 0000 0001 0000 0000 000").one()
    dst = db.query(Account).filter_by(iban_fake="FR76 0000 0000 0002 0000 0000 000").one()
    assert src.monthly_limit_cents is None
    # Un mois de trafic normal au pire (5 req/s, 500 cts) déjà consommé ce mois-ci.
    db.add(
        Transaction(
            src_account=src.id,
            dst_account=dst.id,
            amount_cents=5 * 500 * 86_400 * 31,
            status="created",
            created_at=clock.at,
        )
    )
    src.balance_cents = 10**12
    db.commit()
    client = TestClient(
        create_app(Settings(jwt_secret=JWT_SECRET, run_migrations=False), engine, now=clock)
    )
    r = _send(client, bearer(make_token("demo01")), 100, src=src.id, dst=dst.id)
    assert r.status_code == 201, "verify_tx : jamais limit_exceeded"
