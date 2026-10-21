"""Step-up des gros virements (#51) : seuil, fraîcheur de `auth_time`, rien n'est débité."""

import time

import pytest
from paykit import bearer, make_token
from resilience_db.models import Account, Transaction

from payment_api.config import Settings

TX = "/api/v1/transactions"
BIG = 60_000  # > seuil par défaut (500,00 €)
BODY = {"src_account": 1, "dst_account": 3, "amount_cents": BIG}


@pytest.fixture
def rich(db, world):
    db.get(Account, 1).balance_cents = 1_000_000
    db.commit()


def _h(age_s=None):
    if age_s is None:
        return bearer(make_token("alice", auth_time=None))  # jeton sans auth_time
    return bearer(make_token("alice", auth_time=int(time.time() - age_s)))


def test_under_the_threshold_needs_nothing(client, rich):
    r = client.post(TX, headers=_h(None), json={**BODY, "amount_cents": 50_000})
    assert r.status_code == 201, "au seuil exactement : pas de step-up"


@pytest.mark.parametrize(
    ("age", "expected"), [(10, 201), (299, 201), (301, 403), (None, 403), (-3600, 403)]
)
def test_above_the_threshold_requires_a_recent_password(client, rich, db, age, expected):
    r = client.post(TX, headers=_h(age), json=BODY)
    assert r.status_code == expected
    if expected == 403:
        assert r.json()["error"]["code"] == "step_up_required"
        db.expire_all()
        assert db.query(Transaction).count() == 0, "rien n'est persisté ni débité"
        assert db.get(Account, 1).balance_cents == 1_000_000


def test_step_up_refusal_is_traced(client, rich, log_lines):
    client.post(TX, headers=_h(None), json=BODY)
    (e,) = log_lines("step_up_required")
    assert e["user"] == "alice" and e["http_status"] == 403


def test_scheduled_transfer_creation_is_guarded_too(client, rich):
    from datetime import UTC, datetime

    sched = {**BODY, "frequency": "monthly", "start_on": datetime.now(UTC).date().isoformat()}
    r = client.post("/api/v1/scheduled-transfers", headers=_h(None), json=sched)
    assert r.status_code == 403 and r.json()["error"]["code"] == "step_up_required"
    assert client.post("/api/v1/scheduled-transfers", headers=_h(5), json=sched).status_code == 201


def test_settings_are_bounded():
    with pytest.raises(RuntimeError, match="STEP_UP"):
        Settings(jwt_secret="x" * 40, step_up_max_age_s=10)


def test_verify_tx_stays_under_the_threshold():
    """La transaction de contrôle de la démo ne doit jamais demander de mot de passe."""
    import re
    from pathlib import Path

    src = (Path(__file__).resolve().parents[3] / "scripts" / "verify_tx").read_text(
        encoding="utf-8"
    )
    default = int(re.search(r'VERIFY_AMOUNT_CENTS", "(\d+)"', src).group(1))
    assert default <= Settings(jwt_secret="x" * 40).step_up_threshold_cents
