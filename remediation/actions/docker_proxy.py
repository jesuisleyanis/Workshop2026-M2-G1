"""Client du docker-socket-proxy — le SEUL accès du moteur à Docker.

Le moteur ne monte JAMAIS /var/run/docker.sock. Il parle HTTP au proxy
(http://docker-socket-proxy:2375) qui, lui, filtre les verbes. Par défense en
profondeur, ce client applique en plus sa propre liste blanche (méthode + chemin) :
même un bug ou une injection dans le moteur ne peut pas émettre d'autre appel.

Profil par défaut = RESTART SEUL : GET /_ping, GET /containers/json,
GET /containers/{id}/json, POST /containers/{id}/restart, et POST /containers/{id}/kill
UNIQUEMENT avec `signal=HUP` (rechargement à chaud de Nginx/WAF ; jamais KILL/TERM —
le proxy haproxy applique la même restriction sur le paramètre de requête).
Le profil « recreate » (stop/rename/create/start/delete) n'est actif que si
DOCKER_PROXY_ALLOW_RECREATE=true ET que le proxy a été élargi en conséquence.
"""

from __future__ import annotations

import json
import re
from typing import Any

import httpx

_ID = r"[A-Za-z0-9][A-Za-z0-9_.-]*"

_BASE_ALLOWED: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("GET", re.compile(r"^/_ping$")),
    ("GET", re.compile(r"^/containers/json$")),
    ("GET", re.compile(rf"^/containers/{_ID}/json$")),
    ("POST", re.compile(rf"^/containers/{_ID}/restart$")),
    ("POST", re.compile(rf"^/containers/{_ID}/kill$")),  # signal=HUP seulement (voir _call)
)
_KILL_RX = re.compile(rf"^/containers/{_ID}/kill$")
_RELOAD_SIGNALS = frozenset({"HUP", "SIGHUP"})
_RECREATE_ALLOWED: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("POST", re.compile(rf"^/containers/{_ID}/stop$")),
    ("POST", re.compile(rf"^/containers/{_ID}/rename$")),
    ("POST", re.compile(rf"^/containers/{_ID}/start$")),
    ("POST", re.compile(r"^/containers/create$")),
    ("DELETE", re.compile(rf"^/containers/{_ID}$")),
)


class DockerProxyError(RuntimeError):
    pass


class DockerProxy:
    def __init__(self, http: httpx.AsyncClient, base_url: str, allow_recreate: bool = False) -> None:
        self._http = http
        self._base = base_url.rstrip("/")
        self._allowed = _BASE_ALLOWED + (_RECREATE_ALLOWED if allow_recreate else ())
        self.allow_recreate = allow_recreate

    async def _call(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        ok: tuple[int, ...] = (200, 204),
    ) -> httpx.Response:
        if not any(m == method and rx.match(path) for m, rx in self._allowed):
            raise DockerProxyError(f"appel Docker non autorisé côté client : {method} {path}")
        if _KILL_RX.match(path) and (params or {}).get("signal") not in _RELOAD_SIGNALS:
            raise DockerProxyError("appel Docker non autorisé côté client : kill sans signal=HUP")
        try:
            resp = await self._http.request(
                method, f"{self._base}{path}", params=params, json=json_body, timeout=30.0
            )
        except httpx.HTTPError as exc:
            raise DockerProxyError(f"docker-socket-proxy injoignable ({type(exc).__name__})") from exc
        if resp.status_code not in ok:
            raise DockerProxyError(f"{method} {path} -> HTTP {resp.status_code}")
        return resp

    async def ping(self) -> bool:
        try:
            await self._call("GET", "/_ping")
            return True
        except DockerProxyError:
            return False

    async def find_containers(self, service: str) -> list[str]:
        """Résout un service Compose en identifiants de conteneurs (label compose)."""
        filters = json.dumps({"label": [f"com.docker.compose.service={service}"]})
        resp = await self._call("GET", "/containers/json", params={"all": "true", "filters": filters})
        ids = [c["Id"] for c in resp.json()]
        if not ids:
            raise DockerProxyError(f"aucun conteneur pour le service {service!r}")
        return ids

    async def restart(self, container_id: str, timeout_s: int = 10) -> None:
        await self._call("POST", f"/containers/{container_id}/restart", params={"t": str(timeout_s)})

    async def reload(self, container_id: str) -> None:
        """Rechargement à chaud (SIGHUP au processus principal, ex. `nginx -s reload`)."""
        await self._call("POST", f"/containers/{container_id}/kill", params={"signal": "HUP"}, ok=(204,))

    async def inspect(self, container_id: str) -> dict[str, Any]:
        return (await self._call("GET", f"/containers/{container_id}/json")).json()

    async def recreate(self, container_id: str, image: str | None = None) -> str:
        """Recrée un conteneur depuis son image (rollback si la création échoue)."""
        if not self.allow_recreate:
            raise DockerProxyError("recreate désactivé (proxy en profil restart seul)")
        info = await self.inspect(container_id)
        name = info["Name"].lstrip("/")
        cfg = info.get("Config", {})
        nets = (info.get("NetworkSettings") or {}).get("Networks") or {}
        short = info["Id"][:12]
        body: dict[str, Any] = {
            "Image": image or cfg.get("Image"),
            "Env": cfg.get("Env"),
            "Cmd": cfg.get("Cmd"),
            "Entrypoint": cfg.get("Entrypoint"),
            "Labels": cfg.get("Labels"),
            "User": cfg.get("User") or None,
            "WorkingDir": cfg.get("WorkingDir") or None,
            "ExposedPorts": cfg.get("ExposedPorts"),
            "Healthcheck": cfg.get("Healthcheck"),
            "HostConfig": info.get("HostConfig"),
            "NetworkingConfig": {
                "EndpointsConfig": {
                    n: {"Aliases": [a for a in (v.get("Aliases") or []) if a != short]}
                    for n, v in nets.items()
                }
            },
        }
        body = {k: v for k, v in body.items() if v is not None}
        if not body.get("Image"):
            raise DockerProxyError("image introuvable pour la recréation")
        old_name = f"{name}-old-{short}"
        await self._call("POST", f"/containers/{container_id}/stop", params={"t": "10"}, ok=(204, 304))
        await self._call("POST", f"/containers/{container_id}/rename", params={"name": old_name}, ok=(204,))
        try:
            created = await self._call(
                "POST", "/containers/create", params={"name": name}, json_body=body, ok=(201,)
            )
            new_id = created.json()["Id"]
            await self._call("POST", f"/containers/{new_id}/start", ok=(204, 304))
        except DockerProxyError:
            # Rollback : on remet l'ancien conteneur en service.
            await self._call("POST", f"/containers/{container_id}/rename", params={"name": name}, ok=(204,))
            await self._call("POST", f"/containers/{container_id}/start", ok=(204, 304))
            raise
        await self._call("DELETE", f"/containers/{container_id}", params={"force": "true"}, ok=(204,))
        return new_id
