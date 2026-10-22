"""Client HTTP du service face-id (réseau `app`, authentifié par `X-Internal-Token`).

Un seul objet sert à la fois à la vérification du visage (étape 2 du back-office) et à
l'administration des gabarits (enrôlement, révocation, consultation). `auth` ne voit jamais
d'embedding : face-id ne renvoie que match/no-match et des métadonnées.

Deux délais : `timeout` court pour `verify` (ne pas monopoliser le threadpool partagé avec
`/login`, la boucle ZTR), `enroll_timeout` plus long pour l'enrôlement (3 photos à encoder).
"""

from __future__ import annotations

from urllib.parse import quote

import httpx


class FaceUnavailable(RuntimeError):
    """Le service face-id est injoignable ou a répondu hors contrat (mode dégradé : back-office
    inaccessible par conception)."""


class EnrollmentRejectedError(ValueError):
    """face-id a refusé l'enrôlement (photo illisible, pose incorrecte...). `details` : liste de
    `{pose, reason}` à présenter à l'administrateur."""

    def __init__(self, message: str, details: list[dict]) -> None:
        super().__init__(message)
        self.details = details


class FaceIdClient:
    def __init__(
        self,
        base_url: str,
        token: str,
        timeout: float = 2.0,
        enroll_timeout: float = 20.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._base = base_url.rstrip("/") + "/api/v1"
        self._headers = {"X-Internal-Token": token} if token else {}
        self._timeout = timeout
        self._enroll_timeout = enroll_timeout
        self._http = httpx.Client(transport=transport)

    def _request(
        self, method: str, path: str, *, timeout: float, json=None, params: dict | None = None
    ) -> httpx.Response:
        try:
            return self._http.request(
                method,
                self._base + path,
                json=json,
                params=params,
                headers=self._headers,
                timeout=timeout,
            )
        except httpx.HTTPError as exc:
            raise FaceUnavailable(str(exc)) from exc

    @staticmethod
    def _error_body(resp: httpx.Response) -> dict:
        try:
            body = resp.json().get("error", {})
        except (ValueError, AttributeError):
            return {}
        return body if isinstance(body, dict) else {}

    def verify(self, username: str, frames: list[dict]) -> bool:
        """True si les 3 frames correspondent à l'identifiant. 422 (aucun visage, pose
        incorrecte...) = non-correspondance ; tout autre échec = FaceUnavailable."""
        resp = self._request(
            "POST",
            "/verify",
            timeout=self._timeout,
            json={"username": username, "frames": frames},
        )
        if resp.status_code == 422:
            return False
        if resp.status_code != 200:
            raise FaceUnavailable(f"face-id HTTP {resp.status_code}")
        return bool(resp.json().get("match"))

    def enroll(self, username: str, poses: dict[str, str], enrolled_by: str) -> dict:
        resp = self._request(
            "POST",
            "/enroll",
            timeout=self._enroll_timeout,
            json={"username": username, "enrolled_by": enrolled_by, "poses": poses},
        )
        if resp.status_code == 200:
            return resp.json()
        error = self._error_body(resp)
        if resp.status_code == 422 and error.get("code") == "enrollment_rejected":
            raise EnrollmentRejectedError(
                error.get("message", "enrollment rejected"), list(error.get("details", []))
            )
        if resp.status_code == 404:
            raise LookupError(username)
        raise FaceUnavailable(f"face-id HTTP {resp.status_code}")

    def revoke(self, username: str) -> bool:
        """True si un gabarit a été supprimé, False si l'utilisateur n'était pas enrôlé."""
        resp = self._request("DELETE", f"/enroll/{quote(username, safe='')}", timeout=self._timeout)
        if resp.status_code == 204:
            return True
        if resp.status_code == 404:
            return False
        raise FaceUnavailable(f"face-id HTTP {resp.status_code}")

    def enrollments(self) -> list[dict]:
        resp = self._request("GET", "/enrollments", timeout=self._timeout)
        if resp.status_code != 200:
            raise FaceUnavailable(f"face-id HTTP {resp.status_code}")
        return resp.json()

    def photos(self, username: str, viewer: str) -> dict[str, str] | None:
        """Photos d'enrôlement (b64) ; `viewer` est journalisé côté face-id. None si absent."""
        resp = self._request(
            "GET",
            f"/enrollments/{quote(username, safe='')}/photos",
            timeout=self._enroll_timeout,
            params={"viewer": viewer},
        )
        if resp.status_code == 404:
            return None
        if resp.status_code != 200:
            raise FaceUnavailable(f"face-id HTTP {resp.status_code}")
        return resp.json()["photos"]
