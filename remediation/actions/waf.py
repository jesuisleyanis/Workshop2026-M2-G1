"""Actions WAF : waf_block_ip, waf_blacklist_ip (écriture de la deny-list via le playbook
Ansible `waf_deny_ip.yml`, puis rechargement à chaud du WAF via le docker-socket-proxy)
et confirm_waf_block (lecture seule des logs)."""

from __future__ import annotations

import ipaddress
import time
from typing import Any

import httpx

from actions.base import Action, ActionContext, ActionError, ActionParamError, ActionResult
from actions.docker_proxy import DockerProxyError
from actions.runner import PLAYBOOK_WAF_DENY


def _canonical_ip(value: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
    """IP canonique : replie la notation IPv4-mappée (``::ffff:a.b.c.d``) sur son IPv4,
    sinon la liste blanche `never_block_ips` serait contournable par cette forme."""
    ip = ipaddress.ip_address(str(value))
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        return ip.ipv4_mapped
    return ip


def _check_source(params: dict[str, Any]) -> None:
    source = params.get("source", "from_event")
    if source == "from_event":
        return
    try:
        ipaddress.ip_address(str(source))
    except ValueError as exc:
        raise ActionParamError("param 'source' : 'from_event' ou une IP littérale") from exc


def resolve_source_ip(params: dict[str, Any], ctx: ActionContext) -> str:
    """Détermine l'IP à bloquer et applique les garde-fous (jamais l'infra elle-même)."""
    source = params.get("source", "from_event")
    raw = (ctx.event.source_ip if ctx.event else None) if source == "from_event" else source
    if not raw:
        raise ActionError("aucune IP source dans l'événement (champ source_ip absent)")
    ip = _canonical_ip(str(raw))
    protected = {_canonical_ip(p) for p in ctx.settings.never_block_ips}
    if ip in protected or ip.is_loopback or ip.is_unspecified or ip.is_multicast:
        raise ActionError(f"refus de bloquer l'adresse protégée {ip}")
    return str(ip)


class _WafDeny(Action):
    deny_list: str  # temporary | permanent

    @classmethod
    def check_params(cls, params: dict[str, Any]) -> None:
        _check_source(params)

    async def plan(self, ctx: ActionContext) -> str:
        try:
            target = resolve_source_ip(self.params, ctx)
        except ActionError as exc:
            target = f"<non résolue : {exc}>"
        return f"ajouterait {target} à la liste de deny WAF ({self.deny_list}) puis recharger Nginx"

    async def execute(self, ctx: ActionContext) -> ActionResult:
        ip = resolve_source_ip(self.params, ctx)
        res = await ctx.runner.run_playbook(
            PLAYBOOK_WAF_DENY,
            {"deny_ip": ip, "deny_list": self.deny_list, "incident_id": ctx.incident_id},
            timeout=ctx.settings.action_timeout_s,
        )
        if not res.ok:
            raise ActionError(f"playbook {PLAYBOOK_WAF_DENY} en échec ({res.detail or res.rc})")
        # Idempotent : le playbook (lineinfile) ne duplique pas l'entrée ; changed=False si déjà bloquée,
        # auquel cas Nginx n'a pas besoin d'être rechargé.
        reloaded: list[str] = []
        if res.changed is not False:
            try:
                reloaded = await ctx.docker.find_containers(ctx.settings.waf_service)
                for cid in reloaded:
                    await ctx.docker.reload(cid)  # SIGHUP = `nginx -s reload`, via le proxy
            except DockerProxyError as exc:
                raise ActionError(f"deny-list écrite mais rechargement du WAF impossible : {exc}") from exc
        return ActionResult(ok=True, changed=res.changed,
                            data={"ip": ip, "list": self.deny_list, "reloaded": [c[:12] for c in reloaded]},
                            detail=f"{ip} {'déjà bloquée' if res.changed is False else 'bloquée'} ({self.deny_list})"
                                   + (f", WAF rechargé ({len(reloaded)})" if reloaded else ""))


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
        query = '{service="waf"} |= "waf_blocked"'
        if ctx.event and ctx.event.source_ip:
            query += f' |= "{ctx.event.source_ip}"'  # IP validée (ipaddress) -> pas d'injection LogQL
        now_ns = time.time_ns()
        try:
            resp = await ctx.http.get(
                f"{ctx.settings.loki_url}/loki/api/v1/query_range",
                params={"query": query, "start": str(now_ns - 120 * 10**9), "end": str(now_ns), "limit": "1"},
                timeout=10.0,
            )
            resp.raise_for_status()
            streams = resp.json().get("data", {}).get("result", [])
        except (httpx.HTTPError, ValueError) as exc:
            raise ActionError(f"logs WAF illisibles ({type(exc).__name__})") from exc
        confirmed = any(s.get("values") for s in streams)
        return ActionResult(ok=True, data={"confirmed": confirmed},
                            detail="blocage WAF confirmé" if confirmed else "aucun blocage WAF récent observé")
