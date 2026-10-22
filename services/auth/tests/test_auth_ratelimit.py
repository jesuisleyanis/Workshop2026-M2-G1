"""Rate-limit /login, resserrage par la remédiation, API interne protégée."""

import pytest
from authkit import INTERNAL_TOKEN, WAF_IP, WAF_PEER, sample

LOGIN = "/api/v1/login"
BAD = {"username": "alice", "password": "wrong-wrong"}
HDR = {"X-Internal-Token": INTERNAL_TOKEN}


def _hammer(client, n, headers=None, body=BAD):
    return [client.post(LOGIN, json=body, headers=headers).status_code for _ in range(n)]


def test_login_is_rate_limited_with_429_after_threshold(client, registered):
    codes = _hammer(client, 5)  # limite de test : 3/minute
    assert codes == [401, 401, 401, 429, 429]


def test_rate_limit_emits_event_log_and_metric_and_contract_error(client, registered, log_lines):
    before = sample("resilience_auth_rate_limited_total")
    _hammer(client, 3)
    r = client.post(LOGIN, json=BAD)
    assert r.status_code == 429
    assert r.json()["error"]["code"] == "rate_limited"
    assert r.headers["Retry-After"] == "60"
    assert sample("resilience_auth_rate_limited_total") == before + 1
    (entry,) = log_lines("auth_rate_limited")
    assert entry["level"] == "WARNING" and entry["http_status"] == 429
    assert entry["service"] == "auth" and entry["request_id"] == r.headers["X-Request-ID"]


def test_rate_limit_is_per_client_ip(waf_client, registered):
    assert _hammer(waf_client, 4, headers={"X-Forwarded-For": "10.0.0.1"})[-1] == 429
    assert _hammer(waf_client, 1, headers={"X-Forwarded-For": "10.0.0.2"}) == [
        401
    ]  # autre IP : intacte


def test_spoofed_leftmost_xff_cannot_evade_rate_limit(waf_client, registered):
    """Seule l'entrée ajoutée par le proxy de confiance (la plus à droite) compte."""
    codes = [
        waf_client.post(
            LOGIN, json=BAD, headers={"X-Forwarded-For": f"6.6.6.{i}, 10.9.9.9"}
        ).status_code
        for i in range(4)
    ]
    assert codes[-1] == 429


def test_tighten_requires_internal_token(client):
    assert client.post("/internal/tighten-rate-limit", json={"factor": 0.5}).status_code == 401
    r = client.post(
        "/internal/tighten-rate-limit", json={"factor": 0.5}, headers={"X-Internal-Token": "bad"}
    )
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "invalid_internal_token"


def test_tighten_reduces_limit_by_factor_and_applies_immediately(client, registered):
    r = client.post("/internal/tighten-rate-limit", json={"factor": 0.5}, headers=HDR)
    assert r.status_code == 200
    assert r.json() == {"previous_limit": "3/minute", "current_limit": "1/minute"}  # floor(3*0.5)=1
    assert _hammer(client, 3) == [401, 429, 429]


def test_tighten_never_goes_below_one_per_period(client):
    for _ in range(4):
        r = client.post("/internal/tighten-rate-limit", json={"factor": 0.1}, headers=HDR)
    assert r.json()["current_limit"] == "1/minute"


@pytest.mark.parametrize("factor", [0, -1, 1.5, "x"])
def test_tighten_rejects_invalid_factor(client, factor):
    assert (
        client.post(
            "/internal/tighten-rate-limit", json={"factor": factor}, headers=HDR
        ).status_code
        == 422
    )


def test_reset_restores_baseline_limit(client):
    client.post("/internal/tighten-rate-limit", json={"factor": 0.1}, headers=HDR)
    r = client.post("/internal/reset-rate-limit", headers=HDR)
    assert r.json() == {"previous_limit": "1/minute", "current_limit": "3/minute"}
    assert client.post("/internal/reset-rate-limit").status_code == 401


def test_register_is_rate_limited_after_threshold(client):
    """/register est borné (anti-flood de comptes, DoS bcrypt, énumération) — défaut 10/minute."""
    from authkit import PASSWORD

    codes = [
        client.post(
            "/api/v1/register", json={"username": f"u{i:02d}", "password": PASSWORD}
        ).status_code
        for i in range(12)
    ]
    assert codes[:10] == [201] * 10
    assert codes[10] == 429 and codes[11] == 429
    r = client.post("/api/v1/register", json={"username": "u99", "password": PASSWORD})
    assert r.json()["error"]["code"] == "rate_limited"


def test_verification_ip_is_exempt_but_attackers_are_not(engine, registered):
    # verify_tx de la remédiation (IP interne fixe) : jamais bloqué, même après durcissement.
    # Constaté le 21/10 : tighten_rate_limit x5 -> la preuve de reprise échouait au login (escalades).
    from fastapi.testclient import TestClient

    from auth_service.config import Settings
    from auth_service.main import create_app
    from authkit import JWT_SECRET

    settings = Settings(jwt_secret=JWT_SECRET, internal_token=INTERNAL_TOKEN, login_rate_limit="3/minute",
                        run_migrations=False, rate_limit_exempt_ips=("172.31.0.20",),
                        trusted_proxies=(WAF_IP,))
    app = create_app(settings, engine)
    client = TestClient(app, client=WAF_PEER)  # verify_tx passe par le WAF
    client.post("/internal/tighten-rate-limit", json={"factor": 0.1}, headers=HDR)
    assert 429 not in _hammer(client, 6, headers={"X-Forwarded-For": "172.31.0.20"})
    # l'attaquant (passerelle Docker, ou spoof de l'IP exemptée à gauche de X-Forwarded-For) reste limité
    assert _hammer(client, 3, headers={"X-Forwarded-For": "172.31.0.1"})[-1] == 429
    assert _hammer(client, 3, headers={"X-Forwarded-For": "172.31.0.20, 172.31.0.1"})[-1] == 429
    # un conteneur du réseau app qui joint auth EN DIRECT et usurpe l'IP exemptée : XFF ignoré
    rogue = TestClient(app, client=("172.31.0.66", 50000))
    assert _hammer(rogue, 3, headers={"X-Forwarded-For": "172.31.0.20"})[-1] == 429
    assert _hammer(rogue, 1, headers={"X-Forwarded-For": "172.31.0.99"}) == [429]  # même pair


def test_xff_from_an_untrusted_peer_is_ignored(client, waf_client, registered, log_lines):
    _hammer(client, 1, headers={"X-Forwarded-For": "198.51.100.7"})
    _hammer(waf_client, 1, headers={"X-Forwarded-For": "198.51.100.8"})
    ips = [e["client_ip"] for e in log_lines("auth_login_failed")]
    assert ips == ["testclient", "198.51.100.8"]  # pair direct non fiable -> son IP ; WAF -> XFF


def test_trusted_proxies_accept_cidr_and_reject_garbage():
    from starlette.datastructures import Headers

    from auth_service.config import Settings
    from auth_service.observability import client_ip_from, parse_trusted_proxies
    from authkit import JWT_SECRET

    trusted = parse_trusted_proxies("172.31.0.10, 10.0.0.0/8")
    xff = Headers({"x-forwarded-for": "1.2.3.4"})
    assert client_ip_from(xff, "10.4.5.6", 1, trusted) == "1.2.3.4"
    assert client_ip_from(xff, "172.31.0.11", 1, trusted) == "172.31.0.11"
    assert client_ip_from(xff, "172.31.0.10", 1, ()) == "172.31.0.10"  # défaut : aucune confiance
    with pytest.raises(RuntimeError, match="TRUSTED_PROXIES"):
        Settings(jwt_secret=JWT_SECRET, internal_token=INTERNAL_TOKEN, trusted_proxies=("waf",))


def test_tightened_limit_restores_itself_after_the_attack():
    from auth_service.ratelimit import DynamicRateLimit

    now = [0.0]
    rate = DynamicRateLimit("10/minute", restore_after_s=300, clock=lambda: now[0])
    rate.tighten(0.5)
    rate.tighten(0.5)
    assert rate.value == "2/minute"
    now[0] = 299
    assert rate.value == "2/minute"
    now[0] = 300  # plus de durcissement depuis 5 min : retour à la limite de base, sans humain
    assert rate.value == "10/minute"
    assert rate.cost() == DynamicRateLimit("10/minute").cost(), "coût slowapi restauré aussi"
    assert DynamicRateLimit("10/minute", restore_after_s=0).tighten(0.5)[1] == "5/minute"  # 0 = jamais


def test_tightening_keeps_attempts_already_spent(client, registered):
    """Le resserrement ne remet pas le compteur à zéro (la clé slowapi inclut la limite)."""
    assert _hammer(client, 2) == [401, 401]  # 2 essais sur 3
    client.post("/internal/tighten-rate-limit", json={"factor": 0.5}, headers=HDR)  # 3 -> 1
    assert _hammer(client, 1) == [429], "budget déjà consommé : aucun essai neuf offert"


def test_tightened_limit_allows_at_most_the_new_count(client, registered):
    client.post("/internal/tighten-rate-limit", json={"factor": 0.5}, headers=HDR)  # 3 -> 1
    assert _hammer(client, 3) == [401, 429, 429]


def test_other_route_limits_do_not_pollute_the_brute_force_metric(client, log_lines):
    from authkit import PASSWORD

    before = sample("resilience_auth_rate_limited_total")
    for i in range(11):
        r = client.post("/api/v1/register", json={"username": f"v{i:02d}", "password": PASSWORD})
    assert r.status_code == 429
    assert sample("resilience_auth_rate_limited_total") == before, "hors métrique de force brute"
    assert int(r.headers["Retry-After"]) == 60
    (e,) = log_lines("auth_rate_limited")
    assert "10 per 1 minute" in e["message"] and "/api/v1/register" in e["message"]


def test_register_retries_on_a_fake_iban_collision(client, monkeypatch):
    from authkit import PASSWORD

    import auth_service.main as m

    ibans = iter(["FR76 DUPLICATE", "FR76 DUPLICATE", "FR76 FRESH"])
    monkeypatch.setattr(m, "new_fake_iban", lambda: next(ibans))
    assert (
        client.post(
            "/api/v1/register", json={"username": "dupiban01", "password": PASSWORD}
        ).status_code
        == 201
    )
    r = client.post("/api/v1/register", json={"username": "dupiban02", "password": PASSWORD})
    assert r.status_code == 201, "collision d'IBAN : nouvel essai, pas de 503 db_error"


@pytest.mark.parametrize("factor", [0.3, 0.5, 0.7, 0.1])
def test_tightened_budget_is_exact(client, registered, factor):
    import math

    client.post("/internal/tighten-rate-limit", json={"factor": factor}, headers=HDR)
    allowed = max(1, math.floor(3 * factor))  # baseline 3/minute en test
    codes = _hammer(client, allowed + 1)
    assert codes == [401] * allowed + [429], f"exactement {allowed} essais"
