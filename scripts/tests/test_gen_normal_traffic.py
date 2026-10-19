"""Tests du générateur de trafic légitime (aucun réseau : `send` simulé)."""

import importlib.util
import random
import sys
from collections import Counter
from pathlib import Path

import pytest

_PATH = Path(__file__).resolve().parents[1] / "gen_normal_traffic.py"
_spec = importlib.util.spec_from_file_location("gen_normal_traffic", _PATH)
gen = importlib.util.module_from_spec(_spec)
sys.modules["gen_normal_traffic"] = gen  # requis par @dataclass
_spec.loader.exec_module(gen)


class FakeApi:
    """Mini payment-api : un compte par utilisateur, journalise chaque appel."""

    def __init__(self):
        self.calls = []
        self.ids = {u: 100 + i for i, (u, _) in enumerate(gen.USERS)}
        self.passwords = dict(gen.USERS)
        self.expired = set()

    def __call__(self, method, path, payload=None, token=None):
        self.calls.append((method, path, payload, token))
        if path == "/api/v1/login":
            ok = self.passwords.get(payload["username"]) == payload["password"]
            return (200, {"access_token": f"tok-{payload['username']}"}) if ok else (401, {})
        if token is None or token in self.expired:
            return 401, {}
        user = token.removeprefix("tok-")
        if path == "/api/v1/accounts":
            return 200, [{"id": self.ids[user], "iban_fake": "FR-FAKE", "balance_cents": 1}]
        if method == "GET":
            return 200, []
        if payload["dst_account"] not in self.ids.values():
            return 404, {}
        assert isinstance(payload["src_account"], int)  # contrat payment-api : ids entiers
        return 201, {"status": "created"}


def test_action_weights_sum_to_one_and_sampling_follows_them():
    assert sum(w for _, w in gen.ACTIONS) == pytest.approx(1.0)
    rng = random.Random(1)
    counts = Counter(gen.pick_action(rng) for _ in range(20_000))
    for name, weight in gen.ACTIONS:
        assert counts[name] / 20_000 == pytest.approx(weight, abs=0.01)


def test_target_rate_cycles_around_mean():
    rates = [gen.target_rate(t, 5.0) for t in range(0, int(gen.CYCLE_S))]
    assert min(rates) == pytest.approx(5.0 * (1 - gen.AMPLITUDE), rel=0.01)
    assert max(rates) == pytest.approx(5.0 * (1 + gen.AMPLITUDE), rel=0.01)
    assert sum(rates) / len(rates) == pytest.approx(5.0, rel=0.01)
    assert gen.target_rate(0, 0.0) > 0  # jamais de débit nul (expovariate)


def test_client_logs_in_learns_account_then_transfers_to_a_peer():
    api = FakeApi()
    clients = [gen.Client(u, p, send=api) for u, p in gen.USERS]
    for c in clients:
        c.peers = clients
    rng = random.Random(3)
    for c in clients:
        assert c.step(rng, now=0.0) == ("login", 200)
        c.list_accounts()
    assert [c.account_id for c in clients] == [100, 101, 102]

    statuses = Counter()
    for i in range(400):
        action, status = rng.choice(clients).step(rng, now=1.0 + i * 0.1)
        statuses[action, status] += 1
    assert statuses["transfer", 201] > 0
    assert statuses["bad_transfer", 404] > 0          # 4xx légitimes
    assert set(statuses) <= {("accounts", 200), ("history", 200), ("transfer", 201),
                             ("bad_transfer", 404), ("bad_login", 401)}
    transfers = [p for _, path, p, _ in api.calls if path == "/api/v1/transactions" and p]
    assert all(p["src_account"] != p["dst_account"] for p in transfers)


def test_no_transfer_before_account_is_known():
    api = FakeApi()
    c = gen.Client("demo01", "demo-pass-01", send=api)
    c.peers = [c]
    rng = random.Random(0)
    c.step(rng, now=0.0)
    for i in range(50):
        c.step(rng, now=1.0 + i)
    assert not any(path == "/api/v1/transactions" and m == "POST" for m, path, _, _ in api.calls)


def test_session_expiry_and_revoked_token_trigger_relogin():
    api = FakeApi()
    c = gen.Client("demo01", "demo-pass-01", send=api)
    rng = random.Random(0)
    c.step(rng, now=0.0)
    assert c.step(rng, now=gen.SESSION_TTL_S + 1)[0] == "login"  # TTL dépassé

    api.expired.add(c.token)
    while True:
        action, status = c.step(rng, now=gen.SESSION_TTL_S + 2)
        if action != "bad_login":
            break
    assert status == 401 and c.token is None
    assert c.step(rng, now=gen.SESSION_TTL_S + 3) == ("login", 200)


def test_logins_stay_under_the_auth_rate_limit():
    """À 5 req/s, logins (re-logins + fautes de frappe) < 10/min/IP (limite de l'auth)."""
    api = FakeApi()
    t = [0.0]
    stats = gen.run(600, 5.0, api, seed=4, clock=lambda: t[0],
                    sleep=lambda s: t.__setitem__(0, t[0] + s))
    logins = sum(v for k, v in stats.items() if k.startswith(("login:", "bad_login:")))
    assert stats["total"] == pytest.approx(5.0 * 600, rel=0.1)
    assert logins / 10 < 10  # par minute, sur 10 min


def test_parse_duration():
    assert gen.parse_duration("30m") == 1800
    with pytest.raises(ValueError):
        gen.parse_duration("bientôt")
