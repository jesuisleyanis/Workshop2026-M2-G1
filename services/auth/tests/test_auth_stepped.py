"""Tests de l'authentification à étapes du back-office (consigne additionnelle 1, contrat §5.2).

Déterministes : vérificateur de visage stub, notifieur LED capturant, horloge contrôlée.
Aucun réseau ni matériel.
"""

from __future__ import annotations

import jwt
import pytest
from authkit import JWT_SECRET, PASSWORD, sample
from fastapi.testclient import TestClient
from resilience_common.events import RESERVED_EVENTS
from resilience_db import Base, make_engine, make_session_factory
from resilience_db.models import User
from resilience_db.passwords import hash_password

from auth_service.challenge import POSES
from auth_service.config import Settings
from auth_service.face_client import FaceUnavailable
from auth_service.main import create_app

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
    """Reconnaît le visage ssi toutes les images valent GOOD. Peut simuler l'indisponibilité."""

    def __init__(self) -> None:
        self.unavailable = False
        self.calls: list[tuple[str, list[dict]]] = []

    def verify(self, username: str, frames: list[dict]) -> bool:
        self.calls.append((username, frames))
        if self.unavailable:
            raise FaceUnavailable("stub down")
        return all(f["image_b64"] == GOOD for f in frames)


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


def _identify(client, username="op01") -> dict:
    """Étape identifiant : renvoie le JSON complet (challenge_id + poses tirées)."""
    r = client.post("/api/v1/auth/identify", json={"username": username})
    assert r.status_code == 200, r.text
    return r.json()


def frames_for(ident: dict, image: str = GOOD) -> list[dict]:
    """Trois frames dans l'ordre des poses renvoyé par identify."""
    return [{"pose": p, "image_b64": image} for p in ident["poses"]]


def _face(client, ident: dict, image: str = GOOD, frames: list[dict] | None = None):
    return client.post(
        "/api/v1/auth/face",
        json={
            "challenge_id": ident["challenge_id"],
            "frames": frames if frames is not None else frames_for(ident, image),
        },
    )


def _password(client, ident: dict, password: str = PASSWORD):
    return client.post(
        "/api/v1/auth/password", json={"challenge_id": ident["challenge_id"], "password": password}
    )


# --------------------------------------------------------------------------- happy path


def test_full_flow_identify_face_password_returns_token_with_role(client, led):
    ident = _identify(client)
    r = _face(client, ident)
    assert r.json() == {"recognized": True, "step": "password", "attempts_left": 2, "cooldown": 0}
    r = _password(client, ident)
    body = r.json()
    assert r.status_code == 200
    assert body["role"] == "operator"
    claims = jwt.decode(body["access_token"], JWT_SECRET, algorithms=["HS256"])
    assert claims["sub"] == "op01" and claims["role"] == "operator"
    # Séquence LED du contrat §5.3 : idle -> recognized -> auth_ok.
    assert led.states == ["idle", "recognized", "auth_ok"]


# --------------------------------------------------------------------------- poses aléatoires


def test_identify_returns_random_permutation_of_three_poses(client):
    orders = set()
    for _ in range(30):
        poses = tuple(_identify(client)["poses"])
        assert sorted(poses) == sorted(POSES)  # toujours une permutation des 3 poses
        orders.add(poses)
    assert len(orders) >= 2  # tirage aléatoire, pas un ordre fixe


def test_frames_out_of_order_are_rejected_without_calling_face_id(client, face, led):
    ident = _identify(client)
    poses = ident["poses"]
    shuffled = [poses[1], poses[0], poses[2]]  # ordre différent du challenge
    frames = [{"pose": p, "image_b64": GOOD} for p in shuffled]
    r = _face(client, ident, frames=frames)
    assert r.status_code == 200
    body = r.json()
    assert body["recognized"] is False and body["step"] == "identify"
    assert body["cooldown"] == 30
    assert face.calls == []  # face-id n'est jamais appelé
    assert led.states[-1] == "not_recognized"


def test_face_request_requires_exactly_three_frames(client):
    ident = _identify(client)
    two = frames_for(ident)[:2]
    r = _face(client, ident, frames=two)
    assert r.status_code == 422
    four = frames_for(ident) + [{"pose": "face", "image_b64": GOOD}]
    assert _face(client, ident, frames=four).status_code == 422
    bad_pose = [{"pose": "haut", "image_b64": GOOD}] * 3
    assert _face(client, ident, frames=bad_pose).status_code == 422


def test_face_verifier_receives_ordered_frames(client, face):
    ident = _identify(client)
    _face(client, ident)
    assert len(face.calls) == 1
    username, frames = face.calls[0]
    assert username == "op01"
    assert [f["pose"] for f in frames] == ident["poses"]


# --------------------------------------------------------------------------- anti-énumération


def test_identify_unknown_user_still_returns_a_challenge(client):
    # Ne révèle pas l'existence du compte : un identifiant inconnu reçoit aussi un challenge.
    r = client.post("/api/v1/auth/identify", json={"username": "ghost"})
    assert r.status_code == 200
    assert r.json()["step"] == "face"
    assert sorted(r.json()["poses"]) == sorted(POSES)


# --------------------------------------------------------------------------- casse de l'identifiant


def test_identify_is_case_insensitive_and_uses_the_canonical_username(client, engine, face):
    # « lOUIS » atteint le compte « Louis » : face-id et l'étape mot de passe reçoivent le nom
    # canonique stocké en base, pas la saisie.
    with make_session_factory(engine)() as s:
        s.add(User(username="Louis", password_hash=hash_password(PASSWORD), role="admin"))
        s.commit()
    ident = _identify(client, "  lOUIS ")
    assert _face(client, ident).json()["recognized"] is True
    assert [u for u, _ in face.calls] == ["Louis"]
    r = _password(client, ident)
    assert r.status_code == 200
    claims = jwt.decode(r.json()["access_token"], JWT_SECRET, algorithms=["HS256"])
    assert claims["sub"] == "Louis" and r.json()["role"] == "admin"


def test_lockout_is_shared_across_case_variants(client, clock):
    # Changer la casse ne remet pas le compteur à zéro (pas de contournement du verrou).
    assert _face(client, _identify(client, "op01"), BAD).json()["attempts_left"] == 1
    clock.advance(30)
    assert _face(client, _identify(client, "OP01"), BAD).json()["attempts_left"] == 0
    for variant in ("op01", "OP01", "Op01"):
        r = client.post("/api/v1/auth/identify", json={"username": variant})
        assert r.status_code == 429
        assert r.json()["error"]["code"] == "locked_out"


def test_lockout_logs_use_a_case_folded_user(client, clock, log_lines):
    _face(client, _identify(client, "OP01"), BAD)
    clock.advance(30)
    _face(client, _identify(client, "Op01"), BAD)
    started = log_lines("auth_identify_started")
    assert {row["user"] for row in started} == {"op01"}


def test_every_backoffice_step_logs_the_same_case_folded_user(client, engine, clock, log_lines):
    # Champ `user` identique à toutes les étapes (identify, visage, mot de passe) : nom replié,
    # quel que soit le nom canonique en base (« Louis ») ou la casse saisie.
    with make_session_factory(engine)() as s:
        s.add(User(username="Louis", password_hash=hash_password(PASSWORD), role="admin"))
        s.add(User(username="Cust02", password_hash=hash_password(PASSWORD), role="customer"))
        s.commit()
    _face(client, _identify(client, "LOUIS"), BAD)  # auth_face_rejected
    clock.advance(30)
    ident = _identify(client, "lOuIs")
    _face(client, ident)  # auth_face_recognized
    assert _password(client, ident).status_code == 200  # auth_login_success (verrou remis à zéro)
    ident = _identify(client, "louis")
    _face(client, ident)
    assert _password(client, ident, "wrong-password").status_code == 401  # auth_login_failed
    events = ("auth_identify_started", "auth_face_rejected", "auth_face_recognized",
              "auth_login_failed", "auth_login_success")
    rows = [row for row in log_lines() if row["event"] in events]
    assert {row["event"] for row in rows} == set(events)
    assert {row["user"] for row in rows} == {"louis"}
    assert all("Louis" not in row.get("message", "") for row in rows)
    # Rôle non autorisé (403) : même convention.
    clock.advance(30)
    ident = _identify(client, "CUST02")
    _face(client, ident)
    assert _password(client, ident).status_code == 403
    assert log_lines("auth_login_failed")[-1]["user"] == "cust02"


def test_unknown_user_response_is_unchanged_whatever_the_case(client, face):
    # Anti-énumération : même forme de réponse pour un compte inconnu, et le nom saisi est
    # conservé tel quel (rien à résoudre).
    known = client.post("/api/v1/auth/identify", json={"username": "OP01"})
    unknown = client.post("/api/v1/auth/identify", json={"username": "GhOsT"})
    assert known.status_code == unknown.status_code == 200
    assert set(known.json()) == set(unknown.json())
    for key in ("step", "expires_in", "camera"):
        assert known.json()[key] == unknown.json()[key]
    assert sorted(unknown.json()["poses"]) == sorted(POSES)
    ident = unknown.json()
    assert _face(client, ident).json()["recognized"] is True  # le stub ne connaît pas les comptes
    assert face.calls[-1][0] == "GhOsT"
    assert _password(client, ident).status_code == 401


# --------------------------------------------------------------------------- étapes / rejets


def test_cannot_skip_face_step(client):
    ident = _identify(client)  # étape = face
    r = _password(client, ident)
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "wrong_step"


def test_face_not_recognized_clears_flow_and_counts_failure(client, led):
    ident = _identify(client)
    r = _face(client, ident, BAD)
    assert r.json() == {"recognized": False, "step": "identify", "attempts_left": 1, "cooldown": 30}
    assert led.states[-1] == "not_recognized"
    # Le challenge est consommé : on ne peut pas le rejouer.
    again = _face(client, ident, GOOD)
    assert again.status_code == 400


def test_face_challenge_cannot_be_replayed_after_match(client):
    ident = _identify(client)
    assert _face(client, ident).json()["recognized"]
    replay = _face(client, ident)
    assert replay.status_code == 409  # déjà à l'étape password


def test_wrong_password_fails_and_lights_red(client, led):
    ident = _identify(client)
    _face(client, ident)
    r = _password(client, ident, "nope")
    assert r.status_code == 401
    assert led.states[-1] == "auth_fail"


def test_privileged_role_required(client):
    ident = _identify(client, username="cust01")
    _face(client, ident)
    r = _password(client, ident)
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "role_not_authorized"


# --------------------------------------------------------------------------- refroidissements


def test_face_rejection_starts_30s_cooldown_on_identify(client, clock):
    _face(client, _identify(client), BAD)
    r = client.post("/api/v1/auth/identify", json={"username": "op01"})
    assert r.status_code == 429
    assert r.json()["error"]["code"] == "cooldown"
    assert r.headers["Retry-After"] == "30"
    clock.advance(10)
    r = client.post("/api/v1/auth/identify", json={"username": "op01"})
    assert r.status_code == 429 and r.headers["Retry-After"] == "20"
    clock.advance(20)
    assert client.post("/api/v1/auth/identify", json={"username": "op01"}).status_code == 200


def test_wrong_password_starts_3s_cooldown(client, clock):
    ident = _identify(client)
    _face(client, ident)
    r = _password(client, ident, "nope")
    assert r.status_code == 401
    assert r.headers["Retry-After"] == "3"
    blocked = client.post("/api/v1/auth/identify", json={"username": "op01"})
    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "cooldown"
    assert blocked.headers["Retry-After"] == "3"
    clock.advance(3)
    assert client.post("/api/v1/auth/identify", json={"username": "op01"}).status_code == 200


def test_cooldown_logs_auth_cooldown_event(client, log_lines):
    _face(client, _identify(client), BAD)
    client.post("/api/v1/auth/identify", json={"username": "op01"})
    rows = log_lines("auth_cooldown")
    assert len(rows) == 1
    assert rows[0]["http_status"] == 429


def test_cooldown_does_not_affect_another_client_ip(client):
    _face(client, _identify(client), BAD)
    other = client.post(
        "/api/v1/auth/identify",
        json={"username": "op01"},
        headers={"X-Forwarded-For": "203.0.113.9"},
    )
    assert other.status_code == 200


# --------------------------------------------------------------------------- verrouillage


def test_lockout_after_one_retry_then_5_minutes(client, clock):
    before = sample("resilience_auth_lockouts_total")
    # 1er échec : reprise autorisée.
    assert _face(client, _identify(client), BAD).json()["attempts_left"] == 1
    clock.advance(30)  # refroidissement visage écoulé
    # 2e échec : blocage.
    assert _face(client, _identify(client), BAD).json()["attempts_left"] == 0
    assert sample("resilience_auth_lockouts_total") == before + 1
    # Désormais bloqué 5 min : identify renvoie 429 + Retry-After (verrou, pas refroidissement).
    r = client.post("/api/v1/auth/identify", json={"username": "op01"})
    assert r.status_code == 429
    assert r.json()["error"]["code"] == "locked_out"
    assert 30 < int(r.headers["Retry-After"]) <= 300
    # Après expiration du blocage, l'accès est de nouveau possible.
    clock.advance(301)
    assert client.post("/api/v1/auth/identify", json={"username": "op01"}).status_code == 200


def test_lockout_is_enforced_on_prebuilt_challenges(client):
    # B1 : des challenges pré-créés AVANT le blocage ne permettent pas de le contourner.
    pre = [_identify(client) for _ in range(3)]
    _face(client, pre[0], BAD)
    _face(client, pre[1], BAD)  # -> bloqué
    # Le 3e challenge, encore valide, est refusé par le verrou (429), pas traité.
    r = _face(client, pre[2], GOOD)
    assert r.status_code == 429
    assert r.headers.get("Retry-After")


def test_success_resets_the_failure_counter(client, clock):
    # Un échec puis un succès : le compteur repart de zéro.
    _face(client, _identify(client), BAD)
    clock.advance(30)
    ident = _identify(client)
    _face(client, ident)
    _password(client, ident)
    # Nouvel échec : attempts_left de nouveau à 1 (pas 0), le succès a réinitialisé.
    clock.advance(30)
    left = _face(client, _identify(client), BAD).json()["attempts_left"]
    assert left == 1


# --------------------------------------------------------------------------- TTL / disponibilité


def test_expired_challenge_is_rejected(client, clock):
    ident = _identify(client)
    clock.advance(61)  # TTL par défaut = 60 s
    r = _face(client, ident)
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "challenge_invalid"


def test_face_service_unavailable_returns_503(client, face):
    face.unavailable = True
    r = _face(client, _identify(client))
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "face_service_unavailable"


# --------------------------------------------------------------------------- contrats / non-régression


def test_failure_window_forgets_old_failures(client, clock):
    # Fenêtre glissante : un échec isolé et ancien ne compte plus (pas de verrou surprise).
    assert _face(client, _identify(client), BAD).json()["attempts_left"] == 1
    clock.advance(901)  # au-delà de la fenêtre glissante par défaut (900 s)
    r = _face(client, _identify(client), BAD)
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
    assert body["poses"] == []
    r = c.post("/api/v1/auth/password", json={"challenge_id": body["challenge_id"], "password": PASSWORD})
    assert r.status_code == 200 and r.json()["role"] == "operator"


def test_legacy_login_still_works(client):
    # D4 : /login reste la voie des comptes de service (verify_tx, seed) — inchangé.
    r = client.post("/api/v1/login", json={"username": "op01", "password": PASSWORD})
    assert r.status_code == 200
    assert r.json()["token_type"] == "bearer"


def test_default_face_verifier_is_the_exposed_face_client(settings, engine, led, clock):
    # Un seul objet : le client face-id sert à la fois à verify (login) et à l'admin (T5).
    from auth_service.face_client import FaceIdClient

    app = create_app(settings, engine, led_notifier=led, clock=clock)
    assert isinstance(app.state.face_client, FaceIdClient)


def test_all_emitted_events_belong_to_the_contract(settings, engine, face, clock, log_lines):
    led = CapturingLed()
    app = create_app(settings, engine, face_verifier=face, led_notifier=led, clock=clock)
    client = TestClient(app)
    ident = _identify(client)
    _face(client, ident)
    _password(client, ident)
    ident = _identify(client)
    _face(client, ident, BAD)
    client.post("/api/v1/auth/identify", json={"username": "op01"})  # -> auth_cooldown
    emitted = {row["event"] for row in log_lines()}
    assert emitted <= set(RESERVED_EVENTS), f"hors contrat: {emitted - set(RESERVED_EVENTS)}"
    assert {
        "auth_identify_started",
        "auth_face_recognized",
        "auth_face_rejected",
        "auth_cooldown",
    } <= emitted
