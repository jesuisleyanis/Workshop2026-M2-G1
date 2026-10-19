"""tighten_rate_limit : appel de l'API interne du service auth."""

from __future__ import annotations

from typing import Any

import httpx

from actions.base import Action, ActionContext, ActionError, ActionParamError, ActionResult


class TightenRateLimit(Action):
    type = "tighten_rate_limit"

    @classmethod
    def check_params(cls, params: dict[str, Any]) -> None:
        if params.get("service", "auth") != "auth":
            raise ActionParamError("tighten_rate_limit ne supporte que le service 'auth'")
        factor = params.get("factor")
        if isinstance(factor, bool) or not isinstance(factor, (int, float)) or not 0 < factor < 1:
            raise ActionParamError("param 'factor' requis, 0 < factor < 1")

    async def plan(self, ctx: ActionContext) -> str:
        return f"durcirait le rate-limit du service auth (facteur {self.params['factor']})"

    async def execute(self, ctx: ActionContext) -> ActionResult:
        token = ctx.settings.internal_token
        if not token:
            raise ActionError("INTERNAL_TOKEN non configuré")
        try:
            resp = await ctx.http.post(
                f"{ctx.settings.auth_url}/internal/tighten-rate-limit",
                json={"factor": self.params["factor"], "incident_id": ctx.incident_id},
                # Idempotency-Key = incident : un rejeu pour le même incident ne doit pas
                # multiplier le facteur (le service auth doit dédoublonner sur cette clé).
                headers={"X-Internal-Token": token, "Idempotency-Key": ctx.incident_id},
                timeout=10.0,
            )
        except httpx.HTTPError as exc:
            raise ActionError(f"service auth injoignable ({type(exc).__name__})") from exc
        if resp.status_code >= 300:
            raise ActionError(f"auth a refusé tighten-rate-limit (HTTP {resp.status_code})")
        return ActionResult(ok=True, detail=f"rate-limit auth durci (x{self.params['factor']})",
                            data={"factor": self.params["factor"]})
