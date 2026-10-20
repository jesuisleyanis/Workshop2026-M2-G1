"""Tests face-id : vérification 1:1, enrôlement, RGPD (pas de biométrie exposée), contrats.

Déterministes grâce au StubRecognizer (image identique => correspondance, image différente =>
non-correspondance). La qualité de reconnaissance réelle est validée en recette (backend insightface).
"""

from __future__ import annotations

from conftest import AUTH_HEADER, b64
from resilience_common.events import RESERVED_EVENTS

FACE_ALICE = b64(b"visage-de-alice-\x89\x50\x4e\x47")
FACE_BOB = b64(b"visage-de-bob-\x89\x50\x4e\x47")


def _enroll(client, username="alice", image=FACE_ALICE, by="admin01"):
    return client.post(
        "/api/v1/enroll",
        json={"username": username, "images_b64": [image], "enrolled_by": by},
        headers=AUTH_HEADER,
    )


def _verify(client, username="alice", image=FACE_ALICE):
    return client.post(
        "/api/v1/verify", json={"username": username, "image_b64": image}, headers=AUTH_HEADER
    )


def test_health_and_ready_ok(client):
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/ready").json()["status"] == "ready"


def test_verify_requires_internal_token(client, seed_user):
    # Défense en profondeur : /verify n'est appelable que par auth (token interne).
    r = client.post("/api/v1/verify", json={"username": "alice", "image_b64": FACE_ALICE})
    assert r.status_code == 401


def test_enroll_requires_internal_token(client, seed_user):
    r = client.post("/api/v1/enroll", json={"username": "alice", "images_b64": [FACE_ALICE]})
    assert r.status_code == 401


def test_enroll_unknown_user_is_404(client):
    r = _enroll(client, username="ghost")
    assert r.status_code == 404
    assert r.json()["detail"] == "unknown_user"


def test_enroll_then_verify_matches_same_face(client, seed_user):
    assert _enroll(client).status_code == 200
    r = _verify(client, image=FACE_ALICE)
    body = r.json()
    assert r.status_code == 200
    assert body["match"] is True
    assert body["model_version"] == "stub-1.0"
    assert "score" not in body  # le score n'est jamais renvoyé (anti hill-climbing)


def test_verify_rejects_a_different_face(client, seed_user):
    assert _enroll(client).status_code == 200
    assert _verify(client, image=FACE_BOB).json()["match"] is False


def test_verify_unknown_user_is_nomatch_not_404(client):
    # Anti-énumération : un identifiant inconnu se comporte comme un visage non reconnu.
    r = _verify(client, username="ghost", image=FACE_ALICE)
    assert r.status_code == 200
    assert r.json()["match"] is False


def test_verify_rejects_invalid_base64(client):
    r = _verify(client, image="!!not-b64!!")
    assert r.status_code == 422


def test_enrollments_list_exposes_no_biometric_data(client, seed_user):
    assert _enroll(client).status_code == 200
    rows = client.get("/api/v1/enrollments", headers=AUTH_HEADER).json()
    assert len(rows) == 1
    row = rows[0]
    assert row["username"] == "alice"
    assert row["enrolled_by"] == "admin01"
    assert "embedding" not in row  # RGPD : jamais de donnée biométrique renvoyée
    assert "image" not in row


def test_revoke_deletes_enrollment(client, seed_user):
    assert _enroll(client).status_code == 200
    assert client.delete("/api/v1/enroll/alice", headers=AUTH_HEADER).status_code == 204
    # Après révocation : plus d'enrôlement, la vérification ne correspond plus.
    assert client.get("/api/v1/enrollments", headers=AUTH_HEADER).json() == []
    assert _verify(client, image=FACE_ALICE).json()["match"] is False
    assert client.delete("/api/v1/enroll/alice", headers=AUTH_HEADER).status_code == 404


def test_all_emitted_events_belong_to_the_contract(client, seed_user, log_lines):
    _enroll(client)
    _verify(client, image=FACE_ALICE)
    _verify(client, image=FACE_BOB)
    client.delete("/api/v1/enroll/alice", headers=AUTH_HEADER)
    emitted = {row["event"] for row in log_lines()}
    assert emitted  # on a bien capté des événements
    assert emitted <= set(RESERVED_EVENTS), f"événements hors contrat: {emitted - set(RESERVED_EVENTS)}"
    assert {"face_enrolled", "face_verify_match", "face_verify_nomatch", "face_enrollment_revoked"} <= emitted
