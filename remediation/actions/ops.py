"""Actions sans effet sur le SI : dry_run_report et notify_operator."""

from __future__ import annotations

import httpx

from actions.base import Action, ActionContext, ActionResult


class DryRunReport(Action):
    """Journalisation seule (incident `unknown` : jamais d'action destructive)."""

    type = "dry_run_report"
    mutating = False

    async def execute(self, ctx: ActionContext) -> ActionResult:
        e = ctx.event
        top = ", ".join(f.name for f in (e.features_top if e else [])) or "n/a"
        detail = (f"rapport d'anomalie non classée : service={e.service if e else '?'} "
                  f"score={e.anomaly_score if e else '?'} features={top} — aucune action exécutée")
        return ActionResult(ok=True, detail=detail, dry_run=True)


class NotifyOperator(Action):
    """Escalade : log `remediation_failed` + événement dashboard (+ webhook optionnel).

    Ce n'est PAS une intervention dans la boucle de reprise : l'escalade signale un
    échec, elle ne corrige rien.
    """

    type = "notify_operator"
    mutating = False

    async def execute(self, ctx: ActionContext) -> ActionResult:
        reason = str(ctx.extra.get("reason", "échec de remédiation"))
        ctx.log.error(
            f"Escalade opérateur : {reason}",
            extra={"event": "remediation_failed", "incident_id": ctx.incident_id},
        )
        detail = f"opérateur notifié : {reason}"
        url = ctx.settings.notify_webhook_url
        if url:
            try:
                await ctx.http.post(url, json={"incident_id": ctx.incident_id, "reason": reason}, timeout=5.0)
            except httpx.HTTPError:
                detail += " (webhook injoignable)"  # le log + le SSE font foi
        return ActionResult(ok=True, detail=detail, data={"reason": reason})
