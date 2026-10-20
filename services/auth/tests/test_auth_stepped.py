"""Tests de l'authentification à étapes du back-office (consigne additionnelle 1, contrat §5.2).

Déterministes : vérificateur de visage stub, notifieur LED capturant, horloge contrôlée.
Aucun réseau ni matériel.
"""

from __future__ import annotations

import jwt
import pytest
from auth_service.backoffice import FaceUnavailable
from auth_service.config import Settings
from auth_service.main import create_app
from authkit import JWT_SECRET, PASSWORD, sample
from fastapi.testclient import TestClient
from resilience_common.events import RESERVED_EVENTS
from resilience_db import Base, make_engine, make_session_factory
from resilience_db.models import User
from resilience_db.passwords import hash_password

GOOD = "GOOD_FACE"
BAD = "BAD_FACE"


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class StubFaceVerifier:
    """Reconnaît le visage ssi image_b64 == GOOD. Peut simuler l'indisponibilité de face-id."""

    def __init__(self) -> None:
        self.unavailable = False

    def verify(self, username: str, image_b64: str) -> bool:
        if self.unavailable:
            raise FaceUnavailable("stub down")
        return image_b64 == GOOD


class CapturingLed:
    def __init__(self) -> None:
        self.states: list[str] = []

    def publish(self, state: str, challenge_id) -> None:
        self.states.append(state)


@pytest.fixture
def settings():
    return Settings(
        jwt_secret=JWT_SECRET,
        internal_token="internal-token-for-tests",
        face_internal_token="face-internal-token-tests-0123",  # config valide (pas de WARNING)
        login_rate_limit="100/minute",
        backoffice_rate_limit="1000/minute",  # on isole la logique de la limite de débit
        run_migrations=False,
    )


@pytest.fixture
def engine():
    engine = make_engine("sqlite://")
    Base.metadata.create_all(engine)
    with make_session_factory(engine)() as s:
        s.add(User(username="op01", password_hash=hash_password(PASSWORD), role="operator"))
        s.add(User(username="cust01", password_hash=hash_password(PASSWORD), role="customer"))
        s.commit()
    return engine


@pytest.fixture
def face():
    return StubFaceVerifier()


@pytest.fixture
def led():
    return CapturingLed()


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def client(settings, engine, face, led, clock):
    app = create_app(settings, engine, face_verifier=face, led_notifier=led, clock=clock)
    return TestClient(app)


def _identify(client, username="op01"):
    r = client.post("/api/v1/auth/identify", json={"username": username})
    assert r.status_code == 200, r.text
    return r.json()["challenge_id"]


# --------------------------------------------------------------------------- happy path


def test_full_flow_identify_face_password_returns_token_with_role(client, led):
    cid = _identify(client)
    r = client.post("/api/v1/auth/face", json={"challenge_id": cid, "image_b64": GOOD})
    assert r.json() == {"recognized": True, "step": "password", "attempts_left": 2}
    r = client.post("/api/v1/auth/password", json={"challenge_id": cid, "password": PASSWORD})
    body = r.json()
    assert r.status_code == 200
    assert body["role"] == "operator"
    claims = jwt.decode(body["access_token"], JWT_SECRET, algorithms=["HS256"])
    assert claims["sub"] == "op01" and claims["role"] == "operator"
    # Séquence LED du contrat §5.3 : idle -> recognized -> auth_ok.
    assert led.states == ["idle", "recognized", "auth_ok"]


# --------------------------------------------------------------------------- anti-énumération


def test_identify_unknown_user_still_returns_a_challenge(client):
    # Ne révèle pas l'existence du compte : un identifiant inconnu reçoit aussi un challenge.
    r = client.post("/api/v1/auth/identify", json={"username": "ghost"})
    assert r.status_code == 200
    assert r.json()["step"] == "face"


# --------------------------------------------------------------------------- étapes / rejets


def test_cannot_skip_face_step(client):
    cid = _identify(client)  # étape = face
    r = client.post("/api/v1/auth/password", json={"challenge_id": cid, "password": PASSWORD})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "wrong_step"


def test_face_not_recognized_clears_flow_and_counts_failure(client, led):
    cid = _identify(client)
    r = client.post("/api/v1/auth/face", json={"challenge_id": cid, "image_b64": BAD})
    assert r.json() == {"recognized": False, "step": "identify", "attempts_left": 1}
    assert led.states[-1] == "not_recognized"
    # Le challenge est consommé : on ne peut pas le rejouer.
    again = client.post("/api/v1/auth/face", json={"challenge_id": cid, "image_b64": GOOD})
    assert again.status_code == 400


def test_face_challenge_cannot_be_replayed_after_match(client):
    cid = _identify(client)
    assert client.post("/api/v1/auth/face", json={"challenge_id": cid, "image_b64": GOOD}).json()[
        "recognized"
    ]
    replay = client.post("/api/v1/auth/face", json={"challenge_id": cid, "image_b64": GOOD})
    assert replay.status_code == 409  # déjà à l'étape password


def test_wrong_password_fails_and_lights_red(client, led):
    cid = _identify(client)
    client.post("/api/v1/auth/face", json={"challenge_id": cid, "image_b64": GOOD})
    r = client.post("/api/v1/auth/password", json={"challenge_id": cid, "password": "nope"})
    assert r.status_code == 401
    assert led.states[-1] == "auth_fail"


def test_privileged_role_required(client):
    cid = _identify(client, username="cust01")
    client.post("/api/v1/auth/face", json={"challenge_id": cid, "image_b64": GOOD})
    r = client.post("/api/v1/auth/password", json={"challenge_id": cid, "password": PASSWORD})
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "role_not_authorized"


# --------------------------------------------------------------------------- verrouillage


def test_lockout_after_one_retry_then_5_minutes(client, clock):
    before = sample("resilience_auth_lockouts_total")
    # 1er échec : reprise autorisée.
    cid = _identify(client)
    assert client.post(
        "/api/v1/auth/face", json={"challenge_id": cid, "image_b64": BAD}
    ).json()["attempts_left"] == 1
    # 2e échec : blocage.
    cid = _identify(client)
    assert client.post(
        "/api/v1/auth/face", json={"challenge_id": cid, "image_b64": BAD}
    ).json()["attempts_left"] == 0
    assert sample("resilience_auth_lockouts_total") == before + 1
    # Désormais bloqué 5 min : identify renvoie 429 + Retry-After.
    r = client.post("/api/v1/auth/identify", json={"username": "op01"})
    assert r.status_code == 429
    assert 0 < int(r.headers["Retry-After"]) <= 300
    # Après expiration du blocage, l'accès est de nouveau possible.
    clock.advance(301)
    assert client.post("/api/v1/auth/identify", json={"username": "op01"}).status_code == 200


def test_lockout_is_enforced_on_prebuilt_challenges(client):
    # B1 : des challenges pré-créés AVANT le blocage ne permettent pas de le contourner.
    pre = [_identify(client) for _ in range(3)]
    client.post("/api/v1/auth/face", json={"challenge_id": pre[0], "image_b64": BAD})
    client.post("/api/v1/auth/face", json={"challenge_id": pre[1], "image_b64": BAD})  # -> bloqué
    # Le 3e challenge, encore valide, est refusé par le verrou (429), pas traité.
    r = client.post("/api/v1/auth/face", json={"challenge_id": pre[2], "image_b64": GOOD})
    assert r.status_code == 429
    assert r.headers.get("Retry-After")


def test_success_resets_the_failure_counter(client):
    # Un échec puis un succès : le compteur repart de zéro.
    cid = _identify(client)
    client.post("/api/v1/auth/face", json={"challenge_id": cid, "image_b64": BAD})
    cid = _identify(client)
    client.post("/api/v1/auth/face", json={"challenge_id": cid, "image_b64": GOOD})
    client.post("/api/v1/auth/password", json={"challenge_id": cid, "password": PASSWORD})
    # Nouvel échec : attempts_left de nouveau à 1 (pas 0), le succès a réinitialisé.
    cid = _identify(client)
    left = client.post(
        "/api/v1/auth/face", json={"challenge_id": cid, "image_b64": BAD}
    ).json()["attempts_left"]
    assert left == 1


# --------------------------------------------------------------------------- TTL / disponibilité


def test_expired_challenge_is_rejected(client, clock):
    cid = _identify(client)
    clock.advance(61)  # TTL par défaut = 60 s
    r = client.post("/api/v1/auth/face", json={"challenge_id": cid, "image_b64": GOOD})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "challenge_invalid"


def test_face_service_unavailable_returns_503(client, face):
    face.unavailable = True
    cid = _identify(client)
    r = client.post("/api/v1/auth/face", json={"challenge_id": cid, "image_b64": GOOD})
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "face_service_unavailable"


# --------------------------------------------------------------------------- contrats / non-régression


def test_failure_window_forgets_old_failures(client, clock):
    # Fenêtre glissante : un échec isolé et ancien ne compte plus (pas de verrou surprise).
    cid = _identify(client)
    assert client.post(
        "/api/v1/auth/face", json={"challenge_id": cid, "image_b64": BAD}
    ).json()["attempts_left"] == 1
    clock.advance(901)  # au-delà de la fenêtre glissante par défaut (900 s)
    cid = _identify(client)
    r = client.post("/api/v1/auth/face", json={"challenge_id": cid, "image_b64": BAD})
    assert r.status_code == 200
    assert r.json()["attempts_left"] == 1  # le compteur est reparti de zéro


def test_degraded_mode_skips_face_step(settings, engine, face, led, clock):
    # BACKOFFICE_FACE_REQUIRED=false : identify va directement au mot de passe (répétitions de démo).
    import dataclasses

    app = create_app(
        dataclasses.replace(settings, backoffice_face_required=False),
        engine,
        face_verifier=face,
        led_notifier=led,
        clock=clock,
    )
    c = TestClient(app)
    body = c.post("/api/v1/auth/identify", json={"username": "op01"}).json()
    assert body["step"] == "password" and body["camera"] is False
    r = c.post("/api/v1/auth/password", json={"challenge_id": body["challenge_id"], "password": PASSWORD})
    assert r.status_code == 200 and r.json()["role"] == "operator"


def test_legacy_login_still_works(client):
    # D4 : /login reste la voie des comptes de service (verify_tx, seed) — inchangé.
    r = client.post("/api/v1/login", json={"username": "op01", "password": PASSWORD})
    assert r.status_code == 200
    assert r.json()["token_type"] == "bearer"


def test_http_face_verifier_sends_internal_token_and_timeout(monkeypatch):
    # M-a : auth authentifie son appel à face-id et borne le délai.
    import httpx
    from auth_service.backoffice import HttpFaceVerifier

    captured = {}

    class _Resp:
        status_code = 200

        @staticmethod
        def json():
            return {"match": True}

    def fake_post(url, json, headers, timeout):
        captured.update(url=url, headers=headers, timeout=timeout)
        return _Resp()

    monkeypatch.setattr(httpx, "post", fake_post)
    verifier = HttpFaceVerifier("http://face-id:8006", "tok-0123456789abcdef", timeout=1.5)
    assert verifier.verify("op01", "img") is True
    assert captured["headers"]["X-Internal-Token"] == "tok-0123456789abcdef"
    assert captured["timeout"] == 1.5


def test_http_face_verifier_raises_on_auth_failure(monkeypatch):
    # Un 401 de face-id (token absent/incorrect) devient FaceUnavailable -> 503 côté flux.
    import httpx
    from auth_service.backoffice import FaceUnavailable, HttpFaceVerifier

    class _Resp:
        status_code = 401

    monkeypatch.setattr(httpx, "post", lambda *a, **k: _Resp())
    with pytest.raises(FaceUnavailable):
        HttpFaceVerifier("http://face-id:8006", "", timeout=1.0).verify("op01", "img")


def test_all_emitted_events_belong_to_the_contract(settings, engine, face, clock, log_lines):
    led = CapturingLed()
    app = create_app(settings, engine, face_verifier=face, led_notifier=led, clock=clock)
    client = TestClient(app)
    cid = _identify(client)
    client.post("/api/v1/auth/face", json={"challenge_id": cid, "image_b64": GOOD})
    client.post("/api/v1/auth/password", json={"challenge_id": cid, "password": PASSWORD})
    cid = _identify(client)
    client.post("/api/v1/auth/face", json={"challenge_id": cid, "image_b64": BAD})
    emitted = {row["event"] for row in log_lines()}
    assert emitted <= set(RESERVED_EVENTS), f"hors contrat: {emitted - set(RESERVED_EVENTS)}"
    assert {"auth_identify_started", "auth_face_recognized", "auth_face_rejected"} <= emitted
