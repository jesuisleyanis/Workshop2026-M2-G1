"""Tests face-id v2 : enrôlement 3 poses, vérification de séquence, chiffrement, RGPD, contrats.

Déterministes grâce au StubRecognizer : image de test = `<pose>|<identité>` ; l'identité fixe
l'embedding, la pose est lue dans l'image. La qualité réelle (modèle dlib) et les seuils se
valident en recette sur le PC Hôte.
"""

from __future__ import annotations

import base64

import pytest
from conftest import AUTH_HEADER, KEY_B64, TOKEN, b64, img
from face_id.config import Settings
from face_id.main import create_app
from face_id.recognizer import StubRecognizer
from fastapi.testclient import TestClient
from resilience_common.events import RESERVED_EVENTS
from resilience_db.models import FaceEnrollment, User
from sqlalchemy import select

POSES = ("face", "gauche", "droite")


def _series(who="alice", **overrides: str) -> dict[str, str]:
    poses = {pose: img(pose, who) for pose in POSES}
    poses.update(overrides)
    return poses


def _enroll(client, username="alice", poses=None, by="admin01"):
    return client.post(
        "/api/v1/enroll",
        json={"username": username, "enrolled_by": by, "poses": poses or _series(username)},
        headers=AUTH_HEADER,
    )


def _verify(client, username="alice", who="alice", order=POSES, frames=None):
    frames = frames or [{"pose": p, "image_b64": img(p, who)} for p in order]
    return client.post(
        "/api/v1/verify", json={"username": username, "frames": frames}, headers=AUTH_HEADER
    )


def _photos(client, username="alice", **kwargs):
    return client.get(
        f"/api/v1/enrollments/{username}/photos", params={"viewer": "admin01"}, **kwargs
    )


def _error(response) -> dict:
    return response.json()["error"]


# ------------------------------------------------------------------ sondes


def test_health_and_ready_ok(client):
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/ready").json()["status"] == "ready"


def test_metrics_endpoint_exposes_face_metrics(client, seed_user):
    _enroll(client)
    _verify(client)
    text = client.get("/metrics").text
    assert "resilience_face_verifications_total" in text
    assert "resilience_face_enrollments" in text


# ------------------------------------------------------------------ enrôlement


def test_enroll_three_poses_then_verify_in_random_order_matches(client, seed_user):
    r = _enroll(client)
    assert r.status_code == 200
    assert r.json() == {
        "enrolled": True,
        "model_version": "stub-2.0",
        "poses": ["face", "gauche", "droite"],
    }
    for order in (("droite", "face", "gauche"), ("gauche", "droite", "face"), POSES):
        body = _verify(client, order=order).json()
        assert body == {"match": True, "model_version": "stub-2.0"}  # pas de score (hill-climbing)


def test_reenroll_replaces_previous_enrollment(client, seed_user):
    assert _enroll(client, poses=_series("bob")).status_code == 200
    assert _enroll(client).status_code == 200
    assert _verify(client, who="alice").json()["match"] is True
    assert _verify(client, who="bob").json()["match"] is False
    assert len(client.get("/api/v1/enrollments", headers=AUTH_HEADER).json()) == 1


def test_enroll_rejects_whole_series_with_per_pose_details(client, seed_user, log_lines):
    poses = _series(gauche=img("face", "alice"), droite=b64(b"none"))
    r = _enroll(client, poses=poses)
    assert r.status_code == 422
    err = _error(r)
    assert err["code"] == "enrollment_rejected"
    assert err["message"]
    assert sorted(err["details"], key=lambda d: d["pose"]) == [
        {"pose": "droite", "reason": "no_face"},
        {"pose": "gauche", "reason": "wrong_pose"},
    ]
    # Rien n'est enregistré : tout ou rien.
    assert client.get("/api/v1/enrollments", headers=AUTH_HEADER).json() == []
    assert log_lines("face_enrollment_rejected")


def test_enroll_reports_missing_and_invalid_image_poses(client, seed_user):
    poses = _series(droite="!!not-b64!!")
    del poses["gauche"]
    r = _enroll(client, poses=poses)
    assert r.status_code == 422
    details = {d["pose"]: d["reason"] for d in _error(r)["details"]}
    assert details == {"gauche": "missing", "droite": "invalid_image"}


def test_enroll_rejects_inconsistent_identity_across_poses(client, seed_user):
    r = _enroll(client, poses=_series(droite=img("droite", "bob")))
    assert r.status_code == 422
    assert _error(r)["details"] == [{"pose": "droite", "reason": "inconsistent"}]


def test_enroll_rejects_undecodable_thumbnail_as_invalid_image(settings, engine, seed_user):
    def failing(_: bytes) -> bytes:
        raise ValueError("image illisible")

    c = TestClient(create_app(settings, engine, recognizer=StubRecognizer(), thumbnailer=failing))
    r = _enroll(c)
    assert r.status_code == 422
    assert {d["reason"] for d in _error(r)["details"]} == {"invalid_image"}


def test_enroll_with_default_thumbnailer_refuses_non_image_bytes(settings, engine, seed_user):
    # Thumbnailer par défaut (Pillow) : jamais de repli sur les octets d'origine.
    c = TestClient(create_app(settings, engine, recognizer=StubRecognizer()))
    r = _enroll(c)
    assert r.status_code == 422
    assert {d["reason"] for d in _error(r)["details"]} == {"invalid_image"}
    assert c.get("/api/v1/enrollments", headers=AUTH_HEADER).json() == []


def test_enroll_unknown_user_404(client):
    r = _enroll(client, username="ghost")
    assert r.status_code == 404
    assert _error(r)["code"] == "unknown_user"


def test_enroll_requires_internal_token(client, seed_user):
    r = client.post("/api/v1/enroll", json={"username": "alice", "poses": _series()})
    assert r.status_code == 401
    assert _error(r)["code"] == "internal_token_invalid"


def test_enroll_rejects_unknown_pose_key(client, seed_user):
    r = _enroll(client, poses=_series(haut=img("face", "alice")))
    assert r.status_code == 422
    assert _error(r)["code"] == "validation_error"


# ------------------------------------------------------------------ vérification


def test_verify_rejects_other_identity(client, seed_user, log_lines):
    assert _enroll(client).status_code == 200
    assert _verify(client, who="bob").json()["match"] is False
    rows = log_lines("face_verify_nomatch")
    assert rows and "face_mismatch" in rows[-1]["message"]


def test_verify_rejects_wrong_pose_in_sequence(client, seed_user, log_lines):
    assert _enroll(client).status_code == 200
    frames = [
        {"pose": "face", "image_b64": img("face", "alice")},
        {"pose": "gauche", "image_b64": img("droite", "alice")},  # tête tournée du mauvais côté
        {"pose": "droite", "image_b64": img("droite", "alice")},
    ]
    assert _verify(client, frames=frames).json()["match"] is False
    assert "wrong_pose" in log_lines("face_verify_nomatch")[-1]["message"]


def test_verify_without_detectable_face_is_nomatch(client, seed_user):
    assert _enroll(client).status_code == 200
    frames = [
        {"pose": "face", "image_b64": b64(b"none")},
        {"pose": "gauche", "image_b64": img("gauche", "alice")},
        {"pose": "droite", "image_b64": img("droite", "alice")},
    ]
    r = _verify(client, frames=frames)
    assert r.status_code == 200 and r.json()["match"] is False


@pytest.mark.parametrize(
    "poses",
    [
        ["face", "gauche"],  # moins de 3
        ["face", "gauche", "droite", "face"],  # plus de 3
        ["face", "face", "gauche"],  # doublon
        ["face", "gauche", "haut"],  # pose hors contrat
    ],
)
def test_verify_requires_exactly_three_distinct_poses(client, seed_user, poses):
    frames = [{"pose": p, "image_b64": img("face", "alice")} for p in poses]
    r = _verify(client, frames=frames)
    assert r.status_code == 422
    assert _error(r)["code"] == "validation_error"


def test_verify_rejects_invalid_base64(client, seed_user):
    frames = [{"pose": p, "image_b64": "!!not-b64!!"} for p in POSES]
    r = _verify(client, frames=frames)
    assert r.status_code == 422
    assert _error(r)["code"] == "invalid_image"


def test_unknown_user_verify_is_nomatch_not_404(client):
    # Anti-énumération : un identifiant inconnu se comporte comme un visage non reconnu.
    r = _verify(client, username="ghost")
    assert r.status_code == 200
    assert r.json()["match"] is False


def test_verify_requires_internal_token(client, seed_user):
    body = {"username": "alice", "frames": [{"pose": p, "image_b64": img(p, "alice")} for p in POSES]}
    r = client.post("/api/v1/verify", json=body)
    assert r.status_code == 401
    assert _error(r)["code"] == "internal_token_invalid"


def test_model_version_mismatch_is_nomatch_with_error_log(settings, engine, seed_user, log_lines):
    class OtherModel(StubRecognizer):
        model_version = "stub-9.9"

    def identity(b: bytes) -> bytes:
        return b

    old = TestClient(create_app(settings, engine, recognizer=StubRecognizer(), thumbnailer=identity))
    assert _enroll(old).status_code == 200
    new = TestClient(create_app(settings, engine, recognizer=OtherModel(), thumbnailer=identity))
    r = _verify(new)
    assert r.status_code == 200
    assert r.json() == {"match": False, "model_version": "stub-9.9"}
    assert log_lines("face_verify_error")
    # La liste signale la ligne comme inutilisable par le modèle chargé (réenrôlement requis).
    assert [row["usable"] for row in old.get("/api/v1/enrollments", headers=AUTH_HEADER).json()] == [True]
    assert [row["usable"] for row in new.get("/api/v1/enrollments", headers=AUTH_HEADER).json()] == [False]


@pytest.mark.parametrize("model_version", ["stub-1.0", "stub-2.0"])
def test_legacy_v1_row_requires_reenrolment_and_never_crashes(
    client, seed_user, session_factory, log_lines, model_version
):
    # Ligne v1 : embedding float32 brut (non scellé), pas de photos. Avec un autre modèle c'est la
    # garde model_version ; avec le même (stub-2.0) c'est le blob non scellé -> SealError rattrapée.
    with session_factory() as s:
        uid = s.scalar(select(User.id).where(User.username == "alice"))
        s.add(
            FaceEnrollment(
                user_id=uid,
                embedding=b"\x00\x00\x80?" * 16,
                photos=None,
                model_version=model_version,
                enrolled_by="admin01",
            )
        )
        s.commit()
    r = _verify(client)
    assert r.status_code == 200
    assert r.json()["match"] is False
    assert log_lines("face_verify_error")
    rows = client.get("/api/v1/enrollments", headers=AUTH_HEADER).json()
    assert rows[0]["username"] == "alice" and rows[0]["poses"] == ["face"]
    # Ligne v1 (pas de photos) : jamais vérifiable, même si model_version coïncide.
    assert rows[0]["usable"] is False
    # Pas de photos pour une ligne v1 : 404, jamais de 500.
    assert _photos(client, headers=AUTH_HEADER).status_code == 404


# ------------------------------------------------------------------ RGPD / chiffrement


def test_templates_and_photos_are_encrypted_at_rest(client, seed_user, session_factory):
    assert _enroll(client).status_code == 200
    with session_factory() as s:
        row = s.scalar(select(FaceEnrollment))
        assert row.embedding.startswith(b"v1") and row.photos.startswith(b"v1")
        for blob in (row.embedding, row.photos):
            assert b"alice" not in blob
            assert base64.b64encode(b"face|alice") not in blob
        assert row.poses == "face,gauche,droite"


def test_photos_endpoint_requires_token_and_logs_view(client, seed_user, log_lines):
    assert _enroll(client).status_code == 200
    assert _photos(client).status_code == 401
    r = _photos(client, headers=AUTH_HEADER)
    assert r.status_code == 200
    photos = r.json()["photos"]
    assert set(photos) == set(POSES)
    assert base64.b64decode(photos["gauche"]) == b"gauche|alice"  # thumbnailer identité en test
    viewed = log_lines("face_photos_viewed")
    assert len(viewed) == 1
    assert viewed[0]["user"] == "alice" and "admin01" in viewed[0]["message"]


def test_photos_endpoint_404_when_not_enrolled(client, seed_user):
    r = _photos(client, headers=AUTH_HEADER)
    assert r.status_code == 404
    assert _error(r)["code"] == "not_enrolled"


def test_enrollments_list_exposes_no_biometric_data(client, seed_user):
    assert _enroll(client).status_code == 200
    rows = client.get("/api/v1/enrollments", headers=AUTH_HEADER).json()
    assert len(rows) == 1
    row = rows[0]
    assert row["username"] == "alice"
    assert row["enrolled_by"] == "admin01"
    assert row["model_version"] == "stub-2.0"
    assert row["poses"] == ["face", "gauche", "droite"]
    assert row["enrolled_at"]
    assert row["usable"] is True
    assert set(row) == {"username", "enrolled_at", "enrolled_by", "model_version", "poses", "usable"}


def test_revoke_deletes_enrollment(client, seed_user):
    assert _enroll(client).status_code == 200
    assert client.delete("/api/v1/enroll/alice", headers=AUTH_HEADER).status_code == 204
    assert client.get("/api/v1/enrollments", headers=AUTH_HEADER).json() == []
    assert _verify(client).json()["match"] is False
    r = client.delete("/api/v1/enroll/alice", headers=AUTH_HEADER)
    assert r.status_code == 404
    assert _error(r)["code"] == "not_enrolled"


def test_logs_never_contain_image_or_embedding(client, seed_user, log_lines):
    assert _enroll(client).status_code == 200
    _verify(client)
    _verify(client, who="bob")
    _photos(client, headers=AUTH_HEADER)
    raw = log_lines.raw()
    assert raw
    for pose in POSES:
        assert img(pose, "alice") not in raw and img(pose, "bob") not in raw
    sample = StubRecognizer().analyze(b"face|alice").embedding
    assert str(sample[0]) not in raw and "embedding" not in raw
    assert KEY_B64 not in raw and TOKEN not in raw


# ------------------------------------------------------------------ configuration / contrat


def test_settings_require_face_data_key(monkeypatch):
    monkeypatch.delenv("FACE_DATA_KEY", raising=False)
    monkeypatch.delenv("FACE_DATA_KEY_FILE", raising=False)
    monkeypatch.setenv("FACE_INTERNAL_TOKEN", TOKEN)
    with pytest.raises(RuntimeError, match="FACE_DATA_KEY"):
        Settings.from_env()
    monkeypatch.setenv("FACE_DATA_KEY", base64.b64encode(b"short").decode())
    with pytest.raises(RuntimeError, match="FACE_DATA_KEY"):
        Settings.from_env()
    monkeypatch.setenv("FACE_DATA_KEY", KEY_B64)
    assert Settings.from_env().face_data_key == KEY_B64


def test_settings_read_face_data_key_from_file(monkeypatch, tmp_path):
    key_file = tmp_path / "face_data_key"
    key_file.write_text(KEY_B64 + "\n")
    monkeypatch.delenv("FACE_DATA_KEY", raising=False)
    monkeypatch.setenv("FACE_DATA_KEY_FILE", str(key_file))
    monkeypatch.setenv("FACE_INTERNAL_TOKEN", TOKEN)
    assert Settings.from_env().face_data_key == KEY_B64


def test_create_app_rejects_invalid_key(engine):
    bad = Settings(
        internal_token=TOKEN,
        recognizer_backend="stub",
        face_data_key="pas-du-base64!",
        run_migrations=False,
    )
    with pytest.raises(ValueError):
        create_app(bad, engine, recognizer=StubRecognizer())


def test_errors_follow_the_contract_format(client):
    r = client.get("/api/v1/nope", headers=AUTH_HEADER)
    assert r.status_code == 404
    assert set(_error(r)) == {"code", "message"}


def test_all_emitted_events_belong_to_the_contract(client, seed_user, log_lines):
    _enroll(client)
    _enroll(client, poses=_series(droite=b64(b"none")))
    _verify(client)
    _verify(client, who="bob")
    _photos(client, headers=AUTH_HEADER)
    client.delete("/api/v1/enroll/alice", headers=AUTH_HEADER)
    emitted = {row["event"] for row in log_lines()}
    assert emitted  # on a bien capté des événements
    assert emitted <= set(RESERVED_EVENTS), f"événements hors contrat: {emitted - set(RESERVED_EVENTS)}"
    assert {
        "face_enrolled",
        "face_enrollment_rejected",
        "face_verify_match",
        "face_verify_nomatch",
        "face_photos_viewed",
        "face_enrollment_revoked",
    } <= emitted


def test_every_log_line_carries_a_reserved_event(settings, engine, seed_user, session_factory, log_lines):
    """Y compris les chemins d'erreur : photos illisibles, readiness KO, erreur non gérée."""
    from dataclasses import replace

    from sqlalchemy import create_engine

    class Exploding(StubRecognizer):
        def analyze(self, image: bytes, *, precise: bool = False):
            raise RuntimeError("panne du modèle")

    client = TestClient(create_app(settings, engine, recognizer=StubRecognizer(), thumbnailer=lambda b: b))
    assert _enroll(client).status_code == 200
    # Photos altérées en base (même modèle) : 404 photos_unavailable + face_verify_error.
    with session_factory() as s:
        s.scalar(select(FaceEnrollment)).photos = b"v1-corrompu"
        s.commit()
    r = _photos(client, headers=AUTH_HEADER)
    assert r.status_code == 404 and _error(r)["code"] == "photos_unavailable"
    unreadable = log_lines("face_verify_error")
    assert unreadable and unreadable[-1]["user"] == "alice"
    # Erreur non gérée (le modèle plante) : 500 au format contrat, journalisée avec un event.
    boom = TestClient(
        create_app(settings, engine, recognizer=Exploding(), thumbnailer=lambda b: b),
        raise_server_exceptions=False,
    )
    r = _verify(boom)
    assert r.status_code == 500 and _error(r)["code"] == "internal_error"
    # Base injoignable : readiness 503 (+ jauge initiale différée, journalisée en DEBUG).
    dead = create_engine("sqlite:///Z:/inexistant/x/y/face.db")
    down = TestClient(create_app(replace(settings, log_level="DEBUG"), dead, recognizer=StubRecognizer()))
    assert down.get("/ready").status_code == 503
    rows = log_lines()
    assert rows
    events = [row["event"] for row in rows]
    assert "log" not in events, "ligne de log sans `event`"
    assert set(events) <= set(RESERVED_EVENTS), set(events) - set(RESERVED_EVENTS)
    assert {"face_verify_error", "db_error"} <= set(events)
    assert "panne du modèle" not in log_lines.raw()  # type d'exception seul, jamais le message
