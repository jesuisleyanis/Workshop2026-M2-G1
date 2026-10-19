"""Actions de disponibilité : restart_service / recreate_service (via docker-socket-proxy)."""

from __future__ import annotations

import re
from typing import Any

from actions.base import Action, ActionContext, ActionError, ActionParamError, ActionResult
from actions.docker_proxy import DockerProxyError

_SERVICE_RX = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,62}$")
_IMAGE_RX = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/@-]{0,200}$")


def _check_service(params: dict[str, Any]) -> None:
    service = params.get("service")
    if not isinstance(service, str) or not _SERVICE_RX.match(service):
        raise ActionParamError("param 'service' requis (nom de service Compose)")


def _check_allowed(ctx: ActionContext, service: str) -> None:
    # Liste blanche : le moteur ne touche ni postgres, ni le proxy, ni lui-même.
    if service not in ctx.settings.restartable_services:
        raise ActionError(f"service {service!r} hors de la liste autorisée {ctx.settings.restartable_services}")


class RestartService(Action):
    type = "restart_service"

    @classmethod
    def check_params(cls, params: dict[str, Any]) -> None:
        _check_service(params)

    async def plan(self, ctx: ActionContext) -> str:
        return f"redémarrerait le(s) conteneur(s) du service {self.params['service']} via docker-socket-proxy"

    async def execute(self, ctx: ActionContext) -> ActionResult:
        service = self.params["service"]
        _check_allowed(ctx, service)
        try:
            ids = await ctx.docker.find_containers(service)
            for cid in ids:
                await ctx.docker.restart(cid)
        except DockerProxyError as exc:
            raise ActionError(str(exc)) from exc
        # Idempotent : l'état final (conteneur démarré) est le même, quel que soit le nombre de rejeux.
        return ActionResult(ok=True, detail=f"service {service} redémarré ({len(ids)} conteneur(s))",
                            data={"service": service, "containers": [c[:12] for c in ids]})


class RecreateService(Action):
    type = "recreate_service"

    @classmethod
    def check_params(cls, params: dict[str, Any]) -> None:
        _check_service(params)
        image = params.get("image")
        if image is not None and (not isinstance(image, str) or not _IMAGE_RX.match(image)):
            raise ActionParamError("param 'image' invalide")

    async def plan(self, ctx: ActionContext) -> str:
        return f"recréerait le service {self.params['service']} depuis son image saine"

    async def execute(self, ctx: ActionContext) -> ActionResult:
        service = self.params["service"]
        _check_allowed(ctx, service)
        try:
            ids = await ctx.docker.find_containers(service)
            new_ids = [await ctx.docker.recreate(cid, self.params.get("image")) for cid in ids]
        except DockerProxyError as exc:
            raise ActionError(str(exc)) from exc
        return ActionResult(ok=True, detail=f"service {service} recréé",
                            data={"service": service, "containers": [c[:12] for c in new_ids]})
