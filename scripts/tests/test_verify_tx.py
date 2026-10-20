"""verify_tx : conformité au contrat transaction de payment-api (TransactionIn = 3 entiers)
et contrat de sortie 0/1. Le transport HTTP est remplacé par un faux client."""
from __future__ import annotations

import pytest

SEED_PASSWORD = "fake-seed-pass"


class FakeApi:
    """Simule auth + payment-api seedés : demo01 (compte 1), demo02 (compte 2)."""

    def __init__(self, *, balance_cents: int = 100_000, down: bool = False):
        self.balance = balance_cents
        self.down = down
        self.posted: list[dict] = []
        self.transactions: list[dict] = []
        self._tokens = {"demo01": "tok-01", "demo02": "tok-02"}
        self._accounts = {"tok-01": [{"id": 1, "iban_fake": "FR76 ...", "balance_cents": balance_cents, "currency": "EUR"}],
                          "tok-02": [{"id": 2, "iban_fake": "FR76 ...", "balance_cents": balance_cents, "currency": "EUR"}]}

    def request(self, method, path, payload=None, token=None):
        if self.down:
            raise self.TransportError("connection refused")
        if (method, path) == ("POST", "/api/v1/login"):
            if payload.get("password") == SEED_PASSWORD and payload.get("username") in self._tokens:
                return 200, {"access_token": self._tokens[payload["username"]], "token_type": "bearer", "expires_in": 900}
            return 401, {"error": {"code": "invalid_credentials", "message": "Invalid credentials"}}
        if (method, path) == ("GET", "/api/v1/accounts"):
            return 200, self._accounts.get(token, [])
        if (method, path) == ("POST", "/api/v1/transactions"):
            self.posted.append(payload)
            if not all(isinstance(payload.get(k), int) for k in ("src_account", "dst_account", "amount_cents")):
                return 422, {"error": {"code": "validation_error", "message": "src_account: Input should be a valid integer"}}
            if payload["amount_cents"] > self.balance:
                return 409, {"error": {"code": "insufficient_funds", "message": "Insufficient funds"}}
            tx = {"id": len(self.transactions) + 1, "status": "created", **payload}
            self.transactions.append(tx)
            return 201, tx
        if (method, path) == ("GET", "/api/v1/transactions"):
            return 200, list(reversed(self.transactions))
        return 404, {"error": {"code": "not_found", "message": path}}


@pytest.fixture
def api(verify_tx):
    FakeApi.TransportError = verify_tx.TransportError
    return FakeApi()


def _run(verify_tx, api, **overrides):
    kwargs = {"user": "demo01", "password": SEED_PASSWORD, "dst_user": "demo02", "dst_account": None, "amount_cents": 100}
    kwargs.update(overrides)
    return verify_tx.run(api, **kwargs)


def test_nominal_posts_contract_body_and_returns_0(verify_tx, api, capsys):
    assert _run(verify_tx, api) == 0
    assert api.posted == [{"src_account": 1, "dst_account": 2, "amount_cents": 100}]  # TransactionIn exact
    assert "OK" in capsys.readouterr().out


def test_dst_account_env_short_circuits_second_login(verify_tx, api):
    assert _run(verify_tx, api, dst_account=2) == 0
    assert api.posted[0]["dst_account"] == 2


def test_insufficient_funds_returns_1_with_clear_message(verify_tx, capsys):
    api = FakeApi(balance_cents=10)
    assert _run(verify_tx, api) == 1
    assert "insufficient_funds" in capsys.readouterr().err


def test_bad_credentials_returns_1(verify_tx, api):
    assert _run(verify_tx, api, password="wrong") == 1


def test_unreachable_service_returns_1(verify_tx):
    api = FakeApi(down=True)
    assert _run(verify_tx, api) == 1


def test_transaction_must_appear_in_history(verify_tx, api):
    orig = api.request

    def request(method, path, payload=None, token=None):
        if (method, path) == ("GET", "/api/v1/transactions"):
            return 200, []
        return orig(method, path, payload, token)

    api.request = request
    assert _run(verify_tx, api) == 1


def test_main_requires_password(verify_tx, monkeypatch, capsys):
    monkeypatch.delenv("VERIFY_PASSWORD", raising=False)
    monkeypatch.delenv("SEED_PASSWORD", raising=False)
    assert verify_tx.main() == 1
    assert "VERIFY_PASSWORD" in capsys.readouterr().err


def test_main_reads_seed_password_and_env(verify_tx, monkeypatch):
    captured = {}

    def fake_run(client, **kwargs):
        captured.update(kwargs, base_url=client.base_url)
        return 0

    monkeypatch.setattr(verify_tx, "run", fake_run)
    monkeypatch.setenv("SEED_PASSWORD", SEED_PASSWORD)
    monkeypatch.setenv("BASE_URL", "https://waf/")
    monkeypatch.setenv("VERIFY_DST_ACCOUNT", "7")
    monkeypatch.delenv("VERIFY_PASSWORD", raising=False)
    assert verify_tx.main() == 0
    assert captured == {"user": "demo01", "password": SEED_PASSWORD, "dst_user": "demo02",
                        "dst_account": 7, "amount_cents": 100, "base_url": "https://waf"}
