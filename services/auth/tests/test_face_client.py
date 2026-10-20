"""Tests du client HTTP face-id (`FaceIdClient`), sans réseau : httpx.MockTransport."""

from __future__ import annotations

import json

import httpx
import pytest

from auth_service.face_client import (
    EnrollmentRejectedError,
    FaceIdClient,
    FaceUnavailable,
)

TOKEN = "face-internal-token-tests-0123"
FRAMES = [
    {"pose": "face", "image_b64": "AAA"},
    {"pose": "gauche", "image_b64": "BBB"},
    {"pose": "droite", "image_b64": "CCC"},
]


def make_client(handler, **kwargs) -> tuple[FaceIdClient, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def wrapped(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    client = FaceIdClient(
        "http://face-id:8006/", TOKEN, transport=httpx.MockTransport(wrapped), **kwargs
    )
    return client, seen


# --------------------------------------------------------------------------- verify


def test_verify_match_sends_token_and_payload():
    client, seen = make_client(
        lambda r: httpx.Response(200, json={"match": True, "model_version": "v1"})
    )
    assert client.verify("op01", FRAMES) is True
    req = seen[0]
    assert req.method == "POST" and str(req.url) == "http://face-id:8006/api/v1/verify"
    assert req.headers["X-Internal-Token"] == TOKEN
    assert json.loads(req.content) == {"username": "op01", "frames": FRAMES}


def test_verify_no_match_is_false():
    client, _ = make_client(lambda r: httpx.Response(200, json={"match": False}))
    assert client.verify("op01", FRAMES) is False


def test_verify_422_is_not_recognized():
    client, _ = make_client(lambda r: httpx.Response(422, json={"error": {"code": "x"}}))
    assert client.verify("op01", FRAMES) is False


@pytest.mark.parametrize("status", [401, 404, 500, 503])
def test_verify_other_status_is_unavailable(status):
    client, _ = make_client(lambda r: httpx.Response(status))
    with pytest.raises(FaceUnavailable):
        client.verify("op01", FRAMES)


def test_verify_network_error_is_unavailable():
    def boom(request):
        raise httpx.ConnectError("down", request=request)

    client, _ = make_client(boom)
    with pytest.raises(FaceUnavailable):
        client.verify("op01", FRAMES)


def test_verify_uses_short_timeout_and_enroll_longer():
    seen_timeouts: list[dict] = []

    def handler(request):
        seen_timeouts.append(dict(request.extensions["timeout"]))
        if request.method == "POST" and request.url.path.endswith("/verify"):
            return httpx.Response(200, json={"match": True})
        return httpx.Response(200, json={"enrolled": True})

    client, _ = make_client(handler, timeout=1.5, enroll_timeout=17.0)
    client.verify("op01", FRAMES)
    client.enroll("op01", {"face": "a", "gauche": "b", "droite": "c"}, "admin1")
    assert seen_timeouts[0]["read"] == 1.5
    assert seen_timeouts[1]["read"] == 17.0


# --------------------------------------------------------------------------- enroll


def test_enroll_ok_returns_body_and_sends_payload():
    body = {"enrolled": True, "model_version": "v1", "poses": ["face", "gauche", "droite"]}
    client, seen = make_client(lambda r: httpx.Response(200, json=body))
    poses = {"face": "a", "gauche": "b", "droite": "c"}
    assert client.enroll("op01", poses, "admin1") == body
    req = seen[0]
    assert str(req.url) == "http://face-id:8006/api/v1/enroll"
    assert req.headers["X-Internal-Token"] == TOKEN
    assert json.loads(req.content) == {"username": "op01", "enrolled_by": "admin1", "poses": poses}


def test_enroll_422_raises_rejected_with_details():
    details = [{"pose": "gauche", "reason": "pose_mismatch"}]
    payload = {"error": {"code": "enrollment_rejected", "message": "m", "details": details}}
    client, _ = make_client(lambda r: httpx.Response(422, json=payload))
    with pytest.raises(EnrollmentRejectedError) as exc:
        client.enroll("op01", {"face": "a", "gauche": "b", "droite": "c"}, "admin1")
    assert exc.value.details == details


def test_enroll_404_raises_lookup_error():
    payload = {"error": {"code": "unknown_user", "message": "m"}}
    client, _ = make_client(lambda r: httpx.Response(404, json=payload))
    with pytest.raises(LookupError):
        client.enroll("ghost", {"face": "a", "gauche": "b", "droite": "c"}, "admin1")


def test_enroll_server_error_is_unavailable():
    client, _ = make_client(lambda r: httpx.Response(500))
    with pytest.raises(FaceUnavailable):
        client.enroll("op01", {"face": "a", "gauche": "b", "droite": "c"}, "admin1")


# --------------------------------------------------------------------------- revoke


def test_revoke_204_true_404_false():
    client, seen = make_client(lambda r: httpx.Response(204))
    assert client.revoke("op01") is True
    assert seen[0].method == "DELETE"
    assert str(seen[0].url) == "http://face-id:8006/api/v1/enroll/op01"
    assert seen[0].headers["X-Internal-Token"] == TOKEN
    client, _ = make_client(lambda r: httpx.Response(404, json={"error": {"code": "unknown_user"}}))
    assert client.revoke("ghost") is False


def test_revoke_server_error_is_unavailable():
    client, _ = make_client(lambda r: httpx.Response(500))
    with pytest.raises(FaceUnavailable):
        client.revoke("op01")


# --------------------------------------------------------------------------- enrollments / photos


def test_enrollments_lists_rows():
    rows = [{"username": "op01", "enrolled_at": "t", "enrolled_by": "a", "model_version": "v1", "poses": ["face"]}]
    client, seen = make_client(lambda r: httpx.Response(200, json=rows))
    assert client.enrollments() == rows
    assert str(seen[0].url) == "http://face-id:8006/api/v1/enrollments"
    assert seen[0].headers["X-Internal-Token"] == TOKEN


def test_photos_sends_viewer_query_param():
    photos = {"face": "a", "gauche": "b", "droite": "c"}
    client, seen = make_client(lambda r: httpx.Response(200, json={"photos": photos}))
    assert client.photos("op01", "admin1") == photos
    req = seen[0]
    assert req.url.path == "/api/v1/enrollments/op01/photos"
    assert req.url.params["viewer"] == "admin1"
    assert req.headers["X-Internal-Token"] == TOKEN


def test_photos_404_is_none():
    client, _ = make_client(lambda r: httpx.Response(404))
    assert client.photos("ghost", "admin1") is None


def test_enrollments_network_error_is_unavailable():
    def boom(request):
        raise httpx.ConnectTimeout("slow", request=request)

    client, _ = make_client(boom)
    with pytest.raises(FaceUnavailable):
        client.enrollments()
