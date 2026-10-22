"""Tests unitaires de la logique d'enrôlement / vérification de séquence (sans HTTP)."""

from __future__ import annotations

import io

import pytest
from face_id.enrollment import (
    EnrollmentRejected,
    PoseIssue,
    build_templates,
    thumbnail,
    verify_sequence,
)
from face_id.recognizer import StubRecognizer
from PIL import Image

REC = StubRecognizer()


def _series(who="alice", **overrides: bytes) -> dict[str, bytes]:
    images = {pose: f"{pose}|{who}".encode() for pose in ("face", "gauche", "droite")}
    images.update(overrides)
    return images


def _issues(exc: pytest.ExceptionInfo[EnrollmentRejected]) -> dict[str, str]:
    return {i.pose: i.reason for i in exc.value.issues}


def test_build_templates_returns_one_template_per_pose():
    templates = build_templates(REC, _series())
    assert set(templates) == {"face", "gauche", "droite"}
    assert all(len(vec) == 16 for vec in templates.values())


def test_build_templates_collects_every_issue():
    images = _series(gauche=b"face|alice", droite=b"none")
    with pytest.raises(EnrollmentRejected) as exc:
        build_templates(REC, images)
    assert _issues(exc) == {"gauche": "wrong_pose", "droite": "no_face"}
    assert all(isinstance(i, PoseIssue) for i in exc.value.issues)


def test_build_templates_flags_missing_and_multiple_faces():
    images = _series(face=b"many")
    del images["droite"]
    with pytest.raises(EnrollmentRejected) as exc:
        build_templates(REC, images)
    assert _issues(exc) == {"face": "multiple_faces", "droite": "missing"}


def test_build_templates_flags_inconsistent_identity():
    images = _series(droite=b"droite|bob")
    with pytest.raises(EnrollmentRejected) as exc:
        build_templates(REC, images)
    assert _issues(exc) == {"droite": "inconsistent"}


def test_build_templates_skips_consistency_when_face_is_unusable():
    # Sans gabarit « face » exploitable, on ne peut pas juger la cohérence : seule l'erreur réelle.
    images = _series(face=b"none", droite=b"droite|bob")
    with pytest.raises(EnrollmentRejected) as exc:
        build_templates(REC, images)
    assert _issues(exc) == {"face": "no_face"}


def _frames(who="alice", order=("droite", "face", "gauche")):
    return [(pose, f"{pose}|{who}".encode()) for pose in order]


def test_verify_sequence_matches_in_any_order():
    templates = build_templates(REC, _series())
    assert verify_sequence(REC, templates, _frames()) == (True, "ok")


@pytest.mark.parametrize(
    ("frames", "reason"),
    [
        (_frames(who="bob"), "face_mismatch"),
        ([("face", b"none")] + _frames(order=("face", "gauche", "droite"))[1:], "no_face"),
        ([("face", b"many")] + _frames(order=("face", "gauche", "droite"))[1:], "multiple_faces"),
        ([("face", b"gauche|alice")] + _frames(order=("face", "gauche", "droite"))[1:], "wrong_pose"),
        (_frames()[:2], "incomplete"),
        ([("face", b"face|alice")] * 3, "incomplete"),
    ],
)
def test_verify_sequence_failure_reasons(frames, reason):
    templates = build_templates(REC, _series())
    assert verify_sequence(REC, templates, frames) == (False, reason)


def test_verify_sequence_incomplete_when_template_missing():
    templates = build_templates(REC, _series())
    del templates["gauche"]
    assert verify_sequence(REC, templates, _frames()) == (False, "incomplete")


def _png(size: tuple[int, int]) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, (200, 30, 30)).save(buf, "PNG")
    return buf.getvalue()


def test_thumbnail_downsizes_longest_side_to_jpeg():
    out = thumbnail(_png((1000, 500)))
    with Image.open(io.BytesIO(out)) as im:
        assert im.format == "JPEG"
        assert im.size == (240, 120)


def test_thumbnail_never_upscales():
    with Image.open(io.BytesIO(thumbnail(_png((100, 80))))) as im:
        assert im.size == (100, 80)


def test_thumbnail_rejects_non_image_bytes():
    with pytest.raises(ValueError):
        thumbnail(b"face|alice")
