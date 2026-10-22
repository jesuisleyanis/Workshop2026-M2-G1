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

    def __init__(self, clock=lambda: 0.0):
        self.calls, self.times, self._clock = [], [], clock
        self.ids = {u: 100 + i for i, (u, _) in enumerate(gen.USERS)}
        self.passwords = dict(gen.USERS)
        self.expired = set()

    def __call__(self, method, path, payload=None, token=None):
        self.calls.append((method, path, payload, token))
        self.times.append(self._clock())
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
    assert all(p["category"] == gen.pick_category(p["amount_cents"]) for p in transfers)


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
    t = [0.0]
    api = FakeApi(clock=lambda: t[0])
    stats = gen.run(600, 5.0, api, seed=4, clock=lambda: t[0],
                    sleep=lambda s: t.__setitem__(0, t[0] + s))
    logins = [t for t, (_, path, _, _) in zip(api.times, api.calls) if path == "/api/v1/login"]
    assert stats["total"] == pytest.approx(5.0 * 600, rel=0.1)
    assert _max_logins_per_minute(logins) <= gen.LOGIN_BUDGET_PER_MIN  # fenêtre glissante


def test_parse_duration():
    assert gen.parse_duration("30m") == 1800
    with pytest.raises(ValueError):
        gen.parse_duration("bientôt")


class FlakyAuth(FakeApi):
    """L'auth renvoie `auth_status` (503, 429...) tant que `down` ; horodate chaque login."""

    def __init__(self, clock, auth_status=503, retry_after=None):
        super().__init__(clock)
        self.clock, self.down = clock, True
        self.auth_status, self.retry_after = auth_status, retry_after
        self.login_times, self.login_users = [], []

    def __call__(self, method, path, payload=None, token=None):
        if path == "/api/v1/login":
            self.login_times.append(self.clock())
            self.login_users.append((payload["username"], self.clock()))
            if self.down:
                return self.auth_status, ({"retry_after": self.retry_after} if self.retry_after else {})
        return super().__call__(method, path, payload, token)


def _simulate(api, t, seconds, rps=5.0):
    return gen.run(seconds, rps, api, seed=9, clock=lambda: t[0],
                   sleep=lambda s: t.__setitem__(0, t[0] + s))


def _max_logins_per_minute(times):
    return max(sum(1 for x in times if s <= x < s + 60) for s in times) if times else 0


@pytest.mark.parametrize("auth_status", [503, 429, 0])
def test_auth_down_does_not_trigger_a_login_storm(auth_status):
    t = [0.0]
    api = FlakyAuth(lambda: t[0], auth_status=auth_status)
    stats = _simulate(api, t, 600)
    assert _max_logins_per_minute(api.login_times) <= 10  # limite de l'auth : 10/min/IP
    assert stats["wait"] > 0                              # les clients se sont tus
    assert not any(k.startswith(("accounts", "transfer", "history")) for k in stats)


def test_retry_after_is_honoured():
    t = [0.0]
    api = FlakyAuth(lambda: t[0], auth_status=429, retry_after="120")
    _simulate(api, t, 600)
    for user, _ in gen.USERS:  # chaque client attend >= 120 s entre deux tentatives
        times = [x for u, x in api.login_users if u == user]
        assert len(times) >= 2
        assert all(b - a >= 120 for a, b in zip(times, times[1:]))


def test_login_budget_sliding_window():
    b = gen.LoginBudget(per_min=2)
    assert b.allow(0)
    b.record(0)
    b.record(10)
    assert not b.allow(30) and b.next_slot(30) == 60
    assert b.allow(60) and b.next_slot(60) == 60


def test_traffic_resumes_when_auth_comes_back():
    t = [0.0]
    api = FlakyAuth(lambda: t[0], auth_status=503)
    _simulate(api, t, 120)            # 2 min de panne
    api.down = False
    stats = Counter()
    clients_stats = gen.run(300, 5.0, api, seed=10, clock=lambda: t[0],
                            sleep=lambda s: t.__setitem__(0, t[0] + s))
    stats.update(clients_stats)
    assert stats["login:200"] == 3                    # chaque client se reconnecte une fois
    assert stats["accounts:200"] + stats["history:200"] > 500


def test_backoff_grows_exponentially_and_resets_on_success():
    api = FakeApi()
    c = gen.Client("demo01", "demo-pass-01", send=api)
    api.passwords["demo01"] = "autre"  # login refusé
    rng = random.Random(0)
    delays = []
    now = 0.0
    for _ in range(6):
        c.login(now, rng=rng)
        delays.append(c.retry_at - now)
        now = c.retry_at
    lo, hi = 1 - gen.BACKOFF_JITTER, 1 + gen.BACKOFF_JITTER
    for i, d in enumerate(delays):
        expected = min(gen.BACKOFF_MAX_S, gen.BACKOFF_BASE_S * 2 ** i)
        assert expected * lo <= d <= expected * hi
    api.passwords["demo01"] = "demo-pass-01"
    assert c.login(now, rng=rng) == 200 and c.login_failures == 0


def test_deliberate_typo_never_pauses_the_session():
    api = FakeApi()
    c = gen.Client("demo01", "demo-pass-01", send=api)
    c.login(0.0)
    token = c.token
    assert c.login(1.0, password="faux") == 401
    assert c.token == token and c.ready(1.0) and c.login_failures == 0


def test_transfers_carry_varied_valid_categories_without_changing_the_rng_stream():
    counts = Counter(gen.pick_category(a) for a in range(1, 501))
    assert set(counts) == {name for name, _ in gen.CATEGORY_MIX}, "toutes les catégories servies"
    assert abs(sum(w for _, w in gen.CATEGORY_MIX) - 1) < 1e-9
    assert counts["food"] > counts["housing"], "pondération respectée"
