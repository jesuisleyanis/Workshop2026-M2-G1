"""Actions WAF : waf_block_ip, waf_blacklist_ip (écriture de la liste de blocage, rechargée par
le WAF lui-même) et confirm_waf_block (lecture seule des logs).

D'où vient l'IP à bloquer (`params.source`, fixé par la table de décision) :
  * `from_event` : `source_ip` de l'événement (le detector ne l'émet pas encore) ;
  * `from_loki`  : la source la plus fréquente des événements `waf_blocked` des 2 dernières
                   minutes (émis par waf-exporter à partir de `$remote_addr`, jamais de
                   X-Forwarded-For, donc non falsifiable par le client) ;
  * une IP littérale.
Dans tous les cas, jamais une adresse protégée (hôte, loopback...).
"""

from __future__ import annotations

import ipaddress
import json
import time
from collections import Counter
from typing import Any

import httpx

from actions.base import Action, ActionContext, ActionError, ActionParamError, ActionResult

SOURCES = ("from_event", "from_loki")
LOKI_WAF_BLOCKED = '{service="waf-exporter"} |= "waf_blocked"'
LOKI_WINDOW_S = 120


def _check_source(params: dict[str, Any]) -> None:
    source = params.get("source", "from_event")
    if source in SOURCES:
        return
    try:
        ipaddress.ip_address(str(source))
    except ValueError as exc:
        raise ActionParamError("param 'source' : 'from_event', 'from_loki' ou une IP littérale") from exc


def guard_ip(raw: object, ctx: ActionContext) -> str:
    """Valide l'IP et applique les garde-fous (jamais l'infra elle-même)."""
    if not raw:
        raise ActionError("aucune IP source dans l'événement (champ source_ip absent)")
    ip = ipaddress.ip_address(str(raw))
    protected = {ipaddress.ip_address(p) for p in ctx.settings.never_block_ips}
    if ip in protected or ip.is_loopback or ip.is_unspecified or ip.is_multicast:
        raise ActionError(f"refus de bloquer l'adresse protégée {ip}")
    return str(ip)


def resolve_source_ip(params: dict[str, Any], ctx: ActionContext) -> str:
    """Variante synchrone (`from_event` ou IP littérale) ; `from_loki` passe par `resolve_target`."""
    source = params.get("source", "from_event")
    if source == "from_loki":
        raise ActionError("source 'from_loki' : résolution asynchrone requise")
    raw = (ctx.event.source_ip if ctx.event else None) if source == "from_event" else source
    return guard_ip(raw, ctx)


async def top_blocked_ip(ctx: ActionContext) -> str | None:
    """Source la plus fréquente des `waf_blocked` récents (Loki), None s'il n'y en a aucun."""
    now_ns = time.time_ns()
    try:
        resp = await ctx.http.get(
            f"{ctx.settings.loki_url}/loki/api/v1/query_range",
            params={"query": LOKI_WAF_BLOCKED, "start": str(now_ns - LOKI_WINDOW_S * 10**9),
                    "end": str(now_ns), "limit": "500"},
            timeout=10.0,
        )
        resp.raise_for_status()
        streams = resp.json().get("data", {}).get("result", [])
    except (httpx.HTTPError, ValueError) as exc:
        raise ActionError(f"logs WAF illisibles ({type(exc).__name__})") from exc
    counts: Counter[str] = Counter()
    for stream in streams:
        for entry in stream.get("values", []):
            try:
                ip = str(ipaddress.ip_address(str(json.loads(entry[1]).get("client_ip", ""))))
            except (ValueError, TypeError, IndexError, AttributeError):
                continue  # ligne non JSON / IP absente ou malformée : ignorée
            counts[ip] += 1
    return counts.most_common(1)[0][0] if counts else None


async def resolve_target(params: dict[str, Any], ctx: ActionContext) -> str:
    if params.get("source", "from_event") != "from_loki":
        return resolve_source_ip(params, ctx)
    ip = await top_blocked_ip(ctx)
    if ip is None:
        raise ActionError(f"aucun événement waf_blocked dans les {LOKI_WINDOW_S}s : source introuvable")
    return guard_ip(ip, ctx)


class _WafDeny(Action):
    deny_list: str  # temporary | permanent

    @classmethod
    def check_params(cls, params: dict[str, Any]) -> None:
        _check_source(params)

    async def plan(self, ctx: ActionContext) -> str:
        if self.params.get("source") == "from_loki":
            target = "la source la plus fréquente des waf_blocked récents (Loki)"
        else:
            try:
                target = resolve_source_ip(self.params, ctx)
            except ActionError as exc:
                target = f"<non résolue : {exc}>"
        return f"ajouterait {target} à la liste de deny WAF ({self.deny_list}) ; le WAF se recharge seul"

    async def execute(self, ctx: ActionContext) -> ActionResult:
        ip = await resolve_target(self.params, ctx)
        if ctx.blocklist is None:
            raise ActionError("liste de blocage non configurée (BLOCKLIST_PATH)")
        res = await ctx.blocklist.add(ip, deny_list=self.deny_list, incident_id=ctx.incident_id)
        # Idempotent : changed=False si l'IP était déjà bloquée.
        return ActionResult(ok=True, changed=res.changed, data={"ip": ip, "list": self.deny_list},
                            detail=f"{ip} {'déjà bloquée' if res.changed is False else 'bloquée'} ({self.deny_list})")


class WafBlockIp(_WafDeny):
    type = "waf_block_ip"
    deny_list = "temporary"


class WafBlacklistIp(_WafDeny):
    type = "waf_blacklist_ip"
    deny_list = "permanent"


class ConfirmWafBlock(Action):
    """Lecture seule : le WAF a-t-il bien bloqué (événement `waf_blocked` dans Loki) ?"""

    type = "confirm_waf_block"
    mutating = False

    async def plan(self, ctx: ActionContext) -> str:
        return "vérifierait la présence d'événements waf_blocked récents dans Loki"

    async def execute(self, ctx: ActionContext) -> ActionResult:
        # Label `service` = nom du service compose (posé par Promtail) : l'event
        # waf_blocked est émis par le conteneur waf-exporter.
        query = LOKI_WAF_BLOCKED
        if ctx.event and ctx.event.source_ip:
            query += f' |= "{ctx.event.source_ip}"'  # IP validée (ipaddress) -> pas d'injection LogQL
        now_ns = time.time_ns()
        try:
            resp = await ctx.http.get(
                f"{ctx.settings.loki_url}/loki/api/v1/query_range",
                params={"query": query, "start": str(now_ns - LOKI_WINDOW_S * 10**9), "end": str(now_ns), "limit": "1"},
                timeout=10.0,
            )
            resp.raise_for_status()
            streams = resp.json().get("data", {}).get("result", [])
        except (httpx.HTTPError, ValueError) as exc:
            raise ActionError(f"logs WAF illisibles ({type(exc).__name__})") from exc
        confirmed = any(s.get("values") for s in streams)
        return ActionResult(ok=True, data={"confirmed": confirmed},
                            detail="blocage WAF confirmé" if confirmed else "aucun blocage WAF récent observé")
