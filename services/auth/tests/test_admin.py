"""Tests de l'API d'administration des habilitations et du bootstrap du premier administrateur.

Déterministes : `FakeFaceClient` en mémoire (aucun réseau), base SQLite en mémoire.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from authkit import JWT_SECRET, PASSWORD
from fastapi.testclient import TestClient
from resilience_common.events import RESERVED_EVENTS
from resilience_db import Base, make_engine, make_session_factory
from resilience_db.models import Account, FaceEnrollment, User
from resilience_db.passwords import hash_password, verify_password
from sqlalchemy import select

from auth_service.config import Settings
from auth_service.face_client import EnrollmentRejectedError, FaceUnavailable
from auth_service.main import create_app
from auth_service.security import create_access_token

BOOTSTRAP_TOKEN = "bootstrap-token-for-tests-0123456789"
POSES = {"face": "IMG_FACE", "gauche": "IMG_GAUCHE", "droite": "IMG_DROITE"}
NEW_PASSWORD = "another-good-password"


class FakeFaceClient:
    """Double en mémoire de `FaceIdClient` (mêmes signatures, mêmes exceptions)."""

    def __init__(self) -> None:
        self.rows: dict[str, dict] = {}
        self.unavailable = False
        self.missing = False  # enroll -> LookupError (404 côté face-id)
        self.enroll_calls: list[tuple[str, dict, str]] = []
        self.photo_calls: list[tuple[str, str]] = []

    def _check(self) -> None:
        if self.unavailable:
            raise FaceUnavailable("fake down")

    def seed(self, username: str, by: str = "seed") -> None:
        self.rows[username] = {
            "username": username,
            "enrolled_at": "2026-10-20T10:00:00+00:00",
            "enrolled_by": by,
            "model_version": "fake-1",
            "poses": ["face", "gauche", "droite"],
        }

    def verify(self, username, frames) -> bool:  # pragma: no cover - non utilisé ici
        self._check()
        return True

    def enroll(self, username, poses, enrolled_by) -> dict:
        self._check()
        self.enroll_calls.append((username, poses, enrolled_by))
        if self.missing:
            raise LookupError(username)
        bad = [p for p, img in poses.items() if img == "BAD"]
        if bad:
            raise EnrollmentRejectedError(
                "enrollment rejected",
                [{"pose": p, "reason": "no_face_detected"} for p in bad],
            )
        self.seed(username, enrolled_by)
        return {"enrolled": True, "model_version": "fake-1", "poses": list(poses)}

    def revoke(self, username) -> bool:
        self._check()
        return self.rows.pop(username, None) is not None

    def enrollments(self) -> list[dict]:
        self._check()
        return list(self.rows.values())

    def photos(self, username, viewer):
        self._check()
        self.photo_calls.append((username, viewer))
        if username not in self.rows:
            return None
        return dict(POSES)


@pytest.fixture
def settings():
    return Settings(
        jwt_secret=JWT_SECRET,
        internal_token="internal-token-for-tests",
        face_internal_token="face-internal-token-tests-0123",
        login_rate_limit="100/minute",
        backoffice_rate_limit="1000/minute",
        backoffice_bootstrap_token=BOOTSTRAP_TOKEN,
        run_migrations=False,
    )


@pytest.fixture
def engine():
    engine = make_engine("sqlite://")
    Base.metadata.create_all(engine)
    with make_session_factory(engine)() as s:
        for name, role in (
            ("admin01", "admin"),
            ("admin02", "admin"),
            ("op01", "operator"),
            ("cust01", "customer"),
        ):
            s.add(User(username=name, password_hash=hash_password(PASSWORD), role=role))
        s.commit()
    return engine


@pytest.fixture
def face():
    fake = FakeFaceClient()
    fake.seed("admin01")  # seul admin enrôlé au départ
    return fake


@pytest.fixture
def client(settings, engine, face):
    return TestClient(create_app(settings, engine, face_client=face))


def bearer(username: str = "admin01", role: str = "admin") -> dict:
    token, _ = create_access_token(username, JWT_SECRET, role=role)
    return {"Authorization": f"Bearer {token}"}


def user_row(engine, username: str) -> User | None:
    with make_session_factory(engine)() as s:
        return s.scalar(select(User).where(User.username == username))


# --------------------------------------------------------------------------- RBAC

ADMIN_ROUTES = [
    ("GET", "/api/v1/admin/users", None),
    (
        "POST",
        "/api/v1/admin/users",
        {"username": "zed01", "password": PASSWORD, "role": "operator"},
    ),
    ("PATCH", "/api/v1/admin/users/op01", {"role": "customer"}),
    ("PUT", "/api/v1/admin/users/op01/face", {"poses": POSES}),
    ("DELETE", "/api/v1/admin/users/admin01/face", None),
    ("GET", "/api/v1/admin/users/admin01/face/photos", None),
]


@pytest.mark.parametrize("method,path,body", ADMIN_ROUTES)
def test_admin_routes_require_a_token(client, method, path, body):
    r = client.request(method, path, json=body)
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "missing_token"


@pytest.mark.parametrize("method,path,body", ADMIN_ROUTES)
def test_admin_routes_forbid_operator(client, method, path, body):
    r = client.request(method, path, json=body, headers=bearer("op01", "operator"))
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "forbidden"


def test_invalid_expired_and_wrongly_signed_tokens_are_401(client):
    assert (
        client.get("/api/v1/admin/users", headers={"Authorization": "Bearer nope"}).status_code
        == 401
    )
    assert (
        client.get("/api/v1/admin/users", headers={"Authorization": "Basic abc"}).status_code == 401
    )
    past = datetime.now(UTC) - timedelta(hours=1)
    expired, _ = create_access_token("admin01", JWT_SECRET, now=past, role="admin")
    r = client.get("/api/v1/admin/users", headers={"Authorization": f"Bearer {expired}"})
    assert r.status_code == 401 and r.json()["error"]["code"] == "invalid_token"
    forged, _ = create_access_token("admin01", "x" * 40, role="admin")
    r = client.get("/api/v1/admin/users", headers={"Authorization": f"Bearer {forged}"})
    assert r.status_code == 401 and r.json()["error"]["code"] == "invalid_token"
    # Jeton valide mais sans claim sub/role (ex. jeton /login classique) : pas un admin.
    plain, _ = create_access_token("admin01", JWT_SECRET)
    r = client.get("/api/v1/admin/users", headers={"Authorization": f"Bearer {plain}"})
    assert r.status_code == 403


def test_demoted_admin_with_still_valid_token_is_forbidden(client, engine):
    # Le jeton (15 min) porte role=admin, mais la base fait foi : le rôle est revalidé.
    with make_session_factory(engine)() as s:
        s.scalar(select(User).where(User.username == "admin02")).role = "operator"
        s.commit()
    r = client.get("/api/v1/admin/users", headers=bearer("admin02"))
    assert r.status_code == 403


def test_deleted_user_token_is_rejected(client):
    r = client.get("/api/v1/admin/users", headers=bearer("ghost"))
    assert r.status_code == 401


# --------------------------------------------------------------------------- liste / création


def test_list_users_includes_enrollment_state(client, face):
    r = client.get("/api/v1/admin/users", headers=bearer())
    assert r.status_code == 200
    rows = {u["username"]: u for u in r.json()}
    assert set(rows) == {"admin01", "admin02", "op01", "cust01"}
    assert rows["admin01"] == {
        "username": "admin01",
        "role": "admin",
        "enrolled": True,
        "enrolled_at": "2026-10-20T10:00:00+00:00",
        "enrolled_by": "seed",
    }
    assert rows["op01"]["enrolled"] is False
    assert rows["op01"]["enrolled_at"] is None and rows["op01"]["enrolled_by"] is None


def test_list_users_face_unavailable_is_503(client, face):
    face.unavailable = True
    r = client.get("/api/v1/admin/users", headers=bearer())
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "face_service_unavailable"


def test_create_user_then_listed_without_bank_account(client, engine):
    body = {"username": "new.op-1", "password": NEW_PASSWORD, "role": "operator"}
    r = client.post("/api/v1/admin/users", json=body, headers=bearer())
    assert r.status_code == 201
    assert r.json() == {"username": "new.op-1", "role": "operator"}
    with make_session_factory(engine)() as s:
        user = s.scalar(select(User).where(User.username == "new.op-1"))
        assert user.role == "operator"
        assert verify_password(NEW_PASSWORD, user.password_hash)
        assert s.scalars(select(Account).where(Account.user_id == user.id)).all() == []
    listed = client.get("/api/v1/admin/users", headers=bearer()).json()
    assert any(u["username"] == "new.op-1" and u["role"] == "operator" for u in listed)


def test_create_user_duplicate_is_409(client):
    body = {"username": "op01", "password": NEW_PASSWORD, "role": "operator"}
    r = client.post("/api/v1/admin/users", json=body, headers=bearer())
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "username_taken"


@pytest.mark.parametrize(
    "body",
    [
        {"username": "zed01", "password": NEW_PASSWORD, "role": "root"},  # rôle invalide
        {"username": "zed01", "password": NEW_PASSWORD},  # rôle manquant
        {"username": "z", "password": NEW_PASSWORD, "role": "operator"},  # username trop court
        {"username": "bad name!", "password": NEW_PASSWORD, "role": "operator"},
        {"username": "zed01", "password": "short", "role": "operator"},  # < 8
        {"username": "zed01", "password": "é" * 40, "role": "operator"},  # > 72 octets
    ],
)
def test_create_user_validation_is_422(client, body):
    r = client.post("/api/v1/admin/users", json=body, headers=bearer())
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "validation_error"


# --------------------------------------------------------------------------- rôle


def test_change_role_updates_db_and_logs(client, engine, log_lines):
    r = client.patch("/api/v1/admin/users/op01", json={"role": "admin"}, headers=bearer())
    assert r.status_code == 200
    assert r.json() == {"username": "op01", "role": "admin"}
    assert user_row(engine, "op01").role == "admin"
    rows = log_lines("admin_role_changed")
    assert len(rows) == 1
    assert rows[0]["user"] == "op01"  # champ user = cible
    assert "admin01" in rows[0]["message"]  # le message mentionne l'acteur


def test_change_role_unknown_user_is_404(client):
    r = client.patch("/api/v1/admin/users/ghost", json={"role": "admin"}, headers=bearer())
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "unknown_user"


def test_change_role_invalid_role_is_422(client):
    r = client.patch("/api/v1/admin/users/op01", json={"role": "root"}, headers=bearer())
    assert r.status_code == 422


def test_last_enrolled_admin_cannot_be_demoted(client, engine):
    r = client.patch("/api/v1/admin/users/admin01", json={"role": "operator"}, headers=bearer())
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "last_admin"
    assert user_row(engine, "admin01").role == "admin"


def test_enrolled_admin_can_be_demoted_when_another_enrolled_admin_exists(client, face, engine):
    face.seed("admin02")
    r = client.patch(
        "/api/v1/admin/users/admin01", json={"role": "operator"}, headers=bearer("admin02")
    )
    assert r.status_code == 200
    assert user_row(engine, "admin01").role == "operator"


def test_unenrolled_admin_can_be_demoted_freely(client, engine):
    # admin02 n'est pas enrôlé : le dernier admin ENRÔLÉ (admin01) reste en place.
    r = client.patch("/api/v1/admin/users/admin02", json={"role": "customer"}, headers=bearer())
    assert r.status_code == 200
    assert user_row(engine, "admin02").role == "customer"


def test_promoting_or_same_role_does_not_need_face_service(client, face):
    face.unavailable = True
    r = client.patch("/api/v1/admin/users/op01", json={"role": "admin"}, headers=bearer())
    assert r.status_code == 200


def test_demotion_guard_face_unavailable_is_503(client, face, engine):
    face.unavailable = True
    r = client.patch("/api/v1/admin/users/admin01", json={"role": "operator"}, headers=bearer())
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "face_service_unavailable"
    assert user_row(engine, "admin01").role == "admin"


# --------------------------------------------------------------------------- enrôlement


def test_enroll_face_relays_poses_and_actor(client, face, log_lines):
    r = client.put("/api/v1/admin/users/op01/face", json={"poses": POSES}, headers=bearer())
    assert r.status_code == 200
    assert r.json() == {"enrolled": True, "model_version": "fake-1"}
    assert face.enroll_calls == [("op01", POSES, "admin01")]  # enrolled_by == sub
    assert face.rows["op01"]["enrolled_by"] == "admin01"
    rows = log_lines("admin_face_enrolled")
    assert len(rows) == 1 and rows[0]["user"] == "op01" and "admin01" in rows[0]["message"]


def test_enroll_face_rejected_relays_details(client, face):
    bad = {**POSES, "gauche": "BAD"}
    r = client.put("/api/v1/admin/users/op01/face", json={"poses": bad}, headers=bearer())
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["code"] == "enrollment_rejected"
    assert err["details"] == [{"pose": "gauche", "reason": "no_face_detected"}]
    assert "op01" not in face.rows


def test_enroll_face_unknown_user_is_404(client, face):
    r = client.put("/api/v1/admin/users/ghost/face", json={"poses": POSES}, headers=bearer())
    assert r.status_code == 404
    assert face.enroll_calls == []


def test_enroll_face_lookup_error_from_face_id_is_404(client, face):
    face.missing = True
    r = client.put("/api/v1/admin/users/op01/face", json={"poses": POSES}, headers=bearer())
    assert r.status_code == 404


def test_enroll_face_unavailable_is_503(client, face):
    face.unavailable = True
    r = client.put("/api/v1/admin/users/op01/face", json={"poses": POSES}, headers=bearer())
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "face_service_unavailable"


@pytest.mark.parametrize(
    "poses",
    [
        {"face": "a", "gauche": "b"},  # pose manquante
        {"face": "a", "gauche": "b", "droite": "c", "haut": "d"},  # pose inconnue
        {"face": "", "gauche": "b", "droite": "c"},  # image vide
    ],
)
def test_enroll_face_payload_must_have_exactly_the_three_poses(client, face, poses):
    r = client.put("/api/v1/admin/users/op01/face", json={"poses": poses}, headers=bearer())
    assert r.status_code == 422
    assert face.enroll_calls == []


# --------------------------------------------------------------------------- révocation


def test_revoke_face_204_and_log(client, face, log_lines):
    face.seed("op01")
    r = client.delete("/api/v1/admin/users/op01/face", headers=bearer())
    assert r.status_code == 204 and r.content == b""
    assert "op01" not in face.rows
    rows = log_lines("admin_face_revoked")
    assert len(rows) == 1 and rows[0]["user"] == "op01" and "admin01" in rows[0]["message"]


def test_revoke_face_not_enrolled_is_404(client):
    r = client.delete("/api/v1/admin/users/op01/face", headers=bearer())
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_enrolled"


def test_last_enrolled_admin_face_cannot_be_revoked(client, face):
    r = client.delete("/api/v1/admin/users/admin01/face", headers=bearer())
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "last_admin"
    assert "admin01" in face.rows


def test_enrolled_admin_face_can_be_revoked_when_another_exists(client, face):
    face.seed("admin02")
    r = client.delete("/api/v1/admin/users/admin01/face", headers=bearer("admin02"))
    assert r.status_code == 204


def test_revoke_face_unavailable_is_503(client, face):
    face.unavailable = True
    r = client.delete("/api/v1/admin/users/op01/face", headers=bearer())
    assert r.status_code == 503


# --------------------------------------------------------------------------- photos


def test_photos_returns_poses_and_logs_viewer(client, face):
    r = client.get("/api/v1/admin/users/admin01/face/photos", headers=bearer("admin02"))
    assert r.status_code == 200
    assert r.json() == {"photos": POSES}
    assert face.photo_calls == [("admin01", "admin02")]


def test_photos_not_enrolled_is_404(client):
    r = client.get("/api/v1/admin/users/op01/face/photos", headers=bearer())
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_enrolled"


# --------------------------------------------------------------------------- bootstrap


@pytest.fixture
def empty_engine():
    """Aucun admin enrôlé, aucun admin du tout : état de première installation."""
    engine = make_engine("sqlite://")
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def boot_face():
    return FakeFaceClient()


@pytest.fixture
def boot(settings, empty_engine, boot_face):
    return TestClient(create_app(settings, empty_engine, face_client=boot_face))


def boot_body(**over) -> dict:
    return {
        "token": BOOTSTRAP_TOKEN,
        "username": "root01",
        "password": NEW_PASSWORD,
        "poses": POSES,
        **over,
    }


def test_bootstrap_status_required_when_no_enrolled_admin_and_token_set(boot):
    r = boot.get("/api/v1/auth/bootstrap")
    assert r.status_code == 200 and r.json() == {"required": True}


def test_bootstrap_status_not_required_with_enrolled_admin(client):
    assert client.get("/api/v1/auth/bootstrap").json() == {"required": False}


def test_bootstrap_status_still_required_if_admins_exist_but_none_enrolled(client, face):
    face.rows.clear()  # admin01/admin02 existent mais personne n'est enrôlé
    assert client.get("/api/v1/auth/bootstrap").json() == {"required": True}


def test_bootstrap_status_not_required_without_configured_token(settings, empty_engine, boot_face):
    from dataclasses import replace

    app = create_app(
        replace(settings, backoffice_bootstrap_token=""), empty_engine, face_client=boot_face
    )
    assert TestClient(app).get("/api/v1/auth/bootstrap").json() == {"required": False}


def test_bootstrap_status_face_unavailable_is_503(boot, boot_face):
    boot_face.unavailable = True
    r = boot.get("/api/v1/auth/bootstrap")
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "face_service_unavailable"


def test_bootstrap_wrong_token_is_403(boot, empty_engine, boot_face):
    r = boot.post("/api/v1/auth/bootstrap", json=boot_body(token="wrong"))
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "bootstrap_denied"
    assert user_row(empty_engine, "root01") is None
    assert boot_face.enroll_calls == []


def test_bootstrap_without_configured_token_is_always_denied(settings, empty_engine, boot_face):
    from dataclasses import replace

    app = create_app(
        replace(settings, backoffice_bootstrap_token=""), empty_engine, face_client=boot_face
    )
    for token in ("", "anything"):
        r = TestClient(app).post("/api/v1/auth/bootstrap", json=boot_body(token=token))
        assert r.status_code == 403
    assert user_row(empty_engine, "root01") is None


def test_bootstrap_denied_when_not_required(client, engine):
    r = client.post("/api/v1/auth/bootstrap", json=boot_body())  # admin01 est déjà enrôlé
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "bootstrap_denied"
    assert user_row(engine, "root01") is None


def test_bootstrap_creates_enrolled_admin_then_not_required(
    boot, empty_engine, boot_face, log_lines
):
    r = boot.post("/api/v1/auth/bootstrap", json=boot_body())
    assert r.status_code == 201
    assert r.json() == {"username": "root01", "role": "admin"}
    user = user_row(empty_engine, "root01")
    assert user.role == "admin" and verify_password(NEW_PASSWORD, user.password_hash)
    assert boot_face.enroll_calls == [("root01", POSES, "root01")]
    assert boot.get("/api/v1/auth/bootstrap").json() == {"required": False}
    rows = log_lines("backoffice_bootstrap")
    assert len(rows) == 1 and rows[0]["user"] == "root01"
    # Une fois consommé, le bootstrap est refusé même avec le bon token.
    again = boot.post("/api/v1/auth/bootstrap", json=boot_body(username="root02"))
    assert again.status_code == 403


@pytest.mark.parametrize("existing_role", ["operator", "admin"])
def test_bootstrap_existing_staff_gets_new_password_and_admin_role(
    boot, empty_engine, existing_role
):
    with make_session_factory(empty_engine)() as s:
        s.add(User(username="root01", password_hash=hash_password(PASSWORD), role=existing_role))
        s.commit()
    r = boot.post("/api/v1/auth/bootstrap", json=boot_body())
    assert r.status_code == 201
    user = user_row(empty_engine, "root01")
    assert user.role == "admin"
    assert verify_password(NEW_PASSWORD, user.password_hash)
    assert not verify_password(PASSWORD, user.password_hash)


def test_bootstrap_refuses_existing_customer_account(boot, empty_engine, boot_face):
    with make_session_factory(empty_engine)() as s:
        s.add(User(username="root01", password_hash=hash_password(PASSWORD), role="customer"))
        s.commit()
    r = boot.post("/api/v1/auth/bootstrap", json=boot_body())
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "bootstrap_denied"
    user = user_row(empty_engine, "root01")
    assert user.role == "customer"
    assert verify_password(PASSWORD, user.password_hash)  # mot de passe inchangé
    assert boot_face.enroll_calls == []  # aucun enrôlement tenté


def test_bootstrap_rejected_enrollment_rolls_back_creation(boot, empty_engine, boot_face):
    r = boot.post("/api/v1/auth/bootstrap", json=boot_body(poses={**POSES, "face": "BAD"}))
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["code"] == "enrollment_rejected"
    assert err["details"] == [{"pose": "face", "reason": "no_face_detected"}]
    assert user_row(empty_engine, "root01") is None  # pas d'utilisateur orphelin
    assert boot.get("/api/v1/auth/bootstrap").json() == {"required": True}


def test_bootstrap_rejected_enrollment_restores_existing_user(boot, empty_engine):
    with make_session_factory(empty_engine)() as s:
        s.add(User(username="root01", password_hash=hash_password(PASSWORD), role="operator"))
        s.commit()
    r = boot.post("/api/v1/auth/bootstrap", json=boot_body(poses={**POSES, "face": "BAD"}))
    assert r.status_code == 422
    user = user_row(empty_engine, "root01")
    assert user.role == "operator"
    assert verify_password(PASSWORD, user.password_hash)


def test_bootstrap_face_unavailable_rolls_back(boot, empty_engine, boot_face):
    # L'état « requis » se calcule d'abord : face-id en panne => 503 avant toute écriture.
    boot_face.unavailable = True
    r = boot.post("/api/v1/auth/bootstrap", json=boot_body())
    assert r.status_code == 503
    assert user_row(empty_engine, "root01") is None


def test_bootstrap_unavailable_during_enroll_rolls_back(boot, empty_engine, boot_face, monkeypatch):
    def flaky(username, poses, enrolled_by):
        raise FaceUnavailable("down mid-enroll")

    monkeypatch.setattr(boot_face, "enroll", flaky)
    r = boot.post("/api/v1/auth/bootstrap", json=boot_body())
    assert r.status_code == 503
    assert user_row(empty_engine, "root01") is None


@pytest.mark.parametrize(
    "over",
    [
        {"username": "x"},
        {"password": "short"},
        {"poses": {"face": "a"}},
    ],
)
def test_bootstrap_payload_validation_is_422(boot, over):
    assert boot.post("/api/v1/auth/bootstrap", json=boot_body(**over)).status_code == 422


def test_bootstrap_is_rate_limited_to_5_per_minute(boot):
    codes = [
        boot.post("/api/v1/auth/bootstrap", json=boot_body(token="wrong")).status_code
        for _ in range(6)
    ]
    assert codes[:5] == [403] * 5
    assert codes[5] == 429


# ------------------------------------------- bootstrap : face-id a stocké mais auth voit un échec


class DbRecordingFaceClient(FakeFaceClient):
    """Modélise face-id réel : `enroll` INSÈRE une ligne `face_enrollments` (FK vers users) puis
    échoue côté réponse (délai dépassé, 5xx après commit, corps illisible)."""

    def __init__(self, engine, failure: Exception) -> None:
        super().__init__()
        self.engine = engine
        self.failure = failure
        self.revoke_calls: list[str] = []
        self.revoke_fails = False

    def enroll(self, username, poses, enrolled_by) -> dict:
        self.enroll_calls.append((username, poses, enrolled_by))
        with make_session_factory(self.engine)() as s:
            uid = s.scalar(select(User.id).where(User.username == username))
            s.add(
                FaceEnrollment(
                    user_id=uid, embedding=b"x", model_version="fake-1", enrolled_by=enrolled_by
                )
            )
            s.commit()
        self.seed(username, enrolled_by)
        raise self.failure

    def revoke(self, username) -> bool:
        self.revoke_calls.append(username)
        if self.revoke_fails:
            raise FaceUnavailable("revoke down")
        with make_session_factory(self.engine)() as s:
            row = s.scalar(select(FaceEnrollment).join(User).where(User.username == username))
            if row is not None:
                s.delete(row)
                s.commit()
        return self.rows.pop(username, None) is not None


def enrollment_count(engine) -> int:
    with make_session_factory(engine)() as s:
        return len(s.scalars(select(FaceEnrollment)).all())


FAILURES = [
    pytest.param(FaceUnavailable("timeout"), id="timeout"),
    pytest.param(ValueError("malformed 200 body"), id="corps-illisible"),
]


@pytest.mark.parametrize("failure", FAILURES)
def test_bootstrap_failure_after_face_id_stored_revokes_and_deletes_new_user(
    settings, empty_engine, failure
):
    face = DbRecordingFaceClient(empty_engine, failure)
    boot = TestClient(create_app(settings, empty_engine, face_client=face))
    r = boot.post("/api/v1/auth/bootstrap", json=boot_body())
    assert r.status_code == 503  # erreur d'origine mappée, pas un 500 (IntegrityError)
    assert r.json()["error"]["code"] == "face_service_unavailable"
    assert face.revoke_calls == ["root01"]
    assert user_row(empty_engine, "root01") is None
    assert enrollment_count(empty_engine) == 0
    assert boot.get("/api/v1/auth/bootstrap").json() == {"required": True}


def test_bootstrap_failure_after_face_id_stored_restores_existing_user(settings, empty_engine):
    with make_session_factory(empty_engine)() as s:
        s.add(User(username="root01", password_hash=hash_password(PASSWORD), role="operator"))
        s.commit()
    face = DbRecordingFaceClient(empty_engine, FaceUnavailable("5xx after commit"))
    boot = TestClient(create_app(settings, empty_engine, face_client=face))
    r = boot.post("/api/v1/auth/bootstrap", json=boot_body())
    assert r.status_code == 503
    user = user_row(empty_engine, "root01")
    assert user.role == "operator" and verify_password(PASSWORD, user.password_hash)
    assert face.revoke_calls == ["root01"]
    assert enrollment_count(empty_engine) == 0  # le gabarit du détenteur du token est supprimé


def test_bootstrap_failure_keeps_template_of_already_enrolled_account(settings, empty_engine):
    # Un opérateur déjà enrôlé (enrôlement légitime antérieur) ne perd pas son gabarit.
    with make_session_factory(empty_engine)() as s:
        s.add(User(username="root01", password_hash=hash_password(PASSWORD), role="operator"))
        s.commit()
    face = DbRecordingFaceClient(empty_engine, FaceUnavailable("timeout"))
    face.seed("root01", by="earlier-admin")
    boot = TestClient(create_app(settings, empty_engine, face_client=face))
    r = boot.post("/api/v1/auth/bootstrap", json=boot_body())
    assert r.status_code == 503
    assert face.revoke_calls == []
    user = user_row(empty_engine, "root01")
    assert user.role == "operator" and verify_password(PASSWORD, user.password_hash)


def test_bootstrap_rollback_failure_is_logged_and_original_error_is_returned(
    settings, empty_engine, log_lines
):
    # revoke en panne : le compte ne peut pas être supprimé (FK) ; on journalise ERROR et on
    # renvoie quand même l'erreur d'origine (503), jamais un 500.
    face = DbRecordingFaceClient(empty_engine, FaceUnavailable("timeout"))
    face.revoke_fails = True
    boot = TestClient(create_app(settings, empty_engine, face_client=face))
    r = boot.post("/api/v1/auth/bootstrap", json=boot_body())
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "face_service_unavailable"
    errors = [row for row in log_lines("backoffice_bootstrap") if row["level"] == "ERROR"]
    assert len(errors) == 1 and errors[0]["user"] == "root01"
    assert NEW_PASSWORD not in json.dumps(errors)


# --------------------------------------------------------------------------- journaux


def test_admin_events_are_reserved_and_never_leak_secrets(client, boot, face, log_lines):
    client.post(
        "/api/v1/admin/users",
        json={"username": "zed01", "password": NEW_PASSWORD, "role": "operator"},
        headers=bearer(),
    )
    client.patch("/api/v1/admin/users/zed01", json={"role": "customer"}, headers=bearer())
    client.put("/api/v1/admin/users/zed01/face", json={"poses": POSES}, headers=bearer())
    client.delete("/api/v1/admin/users/zed01/face", headers=bearer())
    boot.post("/api/v1/auth/bootstrap", json=boot_body())
    rows = log_lines()
    events = {r["event"] for r in rows}
    assert {
        "admin_user_created",
        "admin_role_changed",
        "admin_face_enrolled",
        "admin_face_revoked",
        "backoffice_bootstrap",
    } <= events
    assert events <= RESERVED_EVENTS
    blob = json.dumps(rows)
    for secret in (
        NEW_PASSWORD,
        BOOTSTRAP_TOKEN,
        "IMG_FACE",
        "IMG_GAUCHE",
        "IMG_DROITE",
        JWT_SECRET,
    ):
        assert secret not in blob
    token = bearer()["Authorization"].split(" ", 1)[1]
    assert token not in blob
    assert jwt.decode(token, JWT_SECRET, algorithms=["HS256"])["role"] == "admin"


# --------------------------------------------------------------------------- configuration / jeton


def test_bootstrap_token_is_read_from_env_or_file(tmp_path, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", JWT_SECRET)
    monkeypatch.setenv("INTERNAL_TOKEN", "internal-token-for-tests")
    monkeypatch.delenv("BACKOFFICE_BOOTSTRAP_TOKEN", raising=False)
    monkeypatch.delenv("BACKOFFICE_BOOTSTRAP_TOKEN_FILE", raising=False)
    assert Settings.from_env().backoffice_bootstrap_token == ""  # optionnel : vide => désactivé
    secret_file = tmp_path / "bootstrap"
    secret_file.write_text(BOOTSTRAP_TOKEN + "\n")
    monkeypatch.setenv("BACKOFFICE_BOOTSTRAP_TOKEN_FILE", str(secret_file))
    assert Settings.from_env().backoffice_bootstrap_token == BOOTSTRAP_TOKEN
    monkeypatch.setenv("BACKOFFICE_BOOTSTRAP_TOKEN", "from-env-wins")
    assert Settings.from_env().backoffice_bootstrap_token == "from-env-wins"


def test_decode_access_token_roundtrip_and_rejections():
    from auth_service.security import decode_access_token

    token, _ = create_access_token("admin01", JWT_SECRET, role="admin")
    claims = decode_access_token(token, JWT_SECRET)
    assert claims["sub"] == "admin01" and claims["role"] == "admin"
    with pytest.raises(jwt.InvalidTokenError):
        decode_access_token(token, "y" * 40)
    no_sub = jwt.encode({"exp": datetime.now(UTC) + timedelta(minutes=5)}, JWT_SECRET, "HS256")
    with pytest.raises(jwt.InvalidTokenError):
        decode_access_token(no_sub, JWT_SECRET)
    no_exp = jwt.encode({"sub": "admin01"}, JWT_SECRET, "HS256")
    with pytest.raises(jwt.InvalidTokenError):
        decode_access_token(no_exp, JWT_SECRET)
