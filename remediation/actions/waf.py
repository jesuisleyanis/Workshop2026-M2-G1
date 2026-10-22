"""Actions WAF : waf_block_ip, waf_blacklist_ip (écriture de la deny-list via le playbook
Ansible `waf_deny_ip.yml`, puis rechargement à chaud du WAF via le docker-socket-proxy)
et confirm_waf_block (lecture seule des logs).

D'où vient l'IP à bloquer (`params.source`, fixé par la table de décision) :
  * `from_event` : `source_ip` de l'événement (IP dominante des logs WAF, désignée par le detector,
                   contrat §3 ; absente si aucune IP ne domine) ;
  * `from_loki`  : la source la plus fréquente des événements `waf_blocked` des 2 dernières
                   minutes (émis par waf-exporter à partir du journal d'audit ModSecurity, donc de
                   l'adresse client vue par le WAF, jamais d'un en-tête non approuvé) ;
  * `from_event_or_loki` : `source_ip` si l'événement en porte une, sinon `from_loki` (web_attack) ;
  * une IP littérale.
Dans tous les cas, jamais une adresse protégée (NEVER_BLOCK_IPS, loopback...).

Label Loki `service` = nom du service Compose émetteur (posé par Promtail) : l'événement
`waf_blocked` vient du conteneur `waf-exporter`, pas de `waf`.
"""

from __future__ import annotations

import ipaddress
import json
import time
from collections import Counter
from typing import Any

import httpx

from actions.base import Action, ActionContext, ActionError, ActionParamError, ActionResult
from actions.docker_proxy import DockerProxyError
from actions.runner import PLAYBOOK_WAF_DENY

LOKI_SOURCES = ("from_loki", "from_event_or_loki")
SOURCES = ("from_event", *LOKI_SOURCES)
# `service` = service Compose émetteur (label Promtail) : waf-exporter, pas waf ; `event` = label Promtail.
LOKI_WAF_BLOCKED = '{service="waf-exporter", event="waf_blocked"}'
LOKI_WINDOW_S = 120
LOKI_SCAN_LIMIT = 500  # lignes lues au plus pour élire la source (borne la charge sur Loki)


def _canonical_ip(value: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
    """IP canonique : replie la notation IPv4-mappée (``::ffff:a.b.c.d``) sur son IPv4,
    sinon la liste blanche `never_block_ips` serait contournable par cette forme."""
    ip = ipaddress.ip_address(str(value))
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        return ip.ipv4_mapped
    return ip


def _check_source(params: dict[str, Any]) -> None:
    source = params.get("source", "from_event")
    if source in SOURCES:
        return
    try:
        ipaddress.ip_address(str(source))
    except ValueError as exc:
        raise ActionParamError(
            "param 'source' : 'from_event', 'from_loki', 'from_event_or_loki' ou une IP littérale") from exc


def guard_ip(raw: object, ctx: ActionContext) -> str:
    """Valide l'IP et applique les garde-fous (jamais l'infra elle-même)."""
    if not raw:
        raise ActionError("aucune IP source dans l'événement (champ source_ip absent)")
    ip = _canonical_ip(str(raw))
    if is_protected(ip, ctx.settings.never_block_ips) or ip.is_loopback or ip.is_unspecified or ip.is_multicast:
        raise ActionError(f"refus de bloquer l'adresse protégée {ip}")
    return str(ip)


def is_protected(ip: ipaddress.IPv4Address | ipaddress.IPv6Address, never_block: tuple[str, ...]) -> bool:
    """`never_block` accepte des IP ET des plages CIDR : les réseaux Docker internes (services, dont la
    remédiation elle-même via verify_tx, et la passerelle par laquelle Docker Desktop fait entrer TOUS les
    clients externes) ne doivent jamais être bloqués."""
    for entry in never_block:
        net = ipaddress.ip_network(entry.strip(), strict=False)
        if net.version == 6 and net.prefixlen == 128 and net.network_address.ipv4_mapped:
            net = ipaddress.ip_network(net.network_address.ipv4_mapped)
        if ip.version == net.version and ip in net:
            return True
    return False


def _event_ip(ctx: ActionContext) -> str | None:
    return ctx.event.source_ip if ctx.event else None


def resolve_source_ip(params: dict[str, Any], ctx: ActionContext) -> str:
    """Résolution synchrone (`from_event` ou IP littérale) ; les sources Loki passent par `resolve_target`."""
    source = params.get("source", "from_event")
    if source in LOKI_SOURCES:
        raise ActionError(f"source '{source}' : résolution asynchrone requise")
    raw = _event_ip(ctx) if source == "from_event" else source
    return guard_ip(raw, ctx)


async def _loki_waf_blocked(ctx: ActionContext, query: str, limit: int) -> list[dict[str, Any]]:
    now_ns = time.time_ns()
    try:
        resp = await ctx.http.get(
            f"{ctx.settings.loki_url}/loki/api/v1/query_range",
            params={"query": query, "start": str(now_ns - LOKI_WINDOW_S * 10**9), "end": str(now_ns),
                    "limit": str(limit)},
            timeout=10.0,
        )
        resp.raise_for_status()
        streams = resp.json().get("data", {}).get("result", [])
    except (httpx.HTTPError, ValueError, AttributeError) as exc:
        raise ActionError(f"logs WAF illisibles ({type(exc).__name__})") from exc
    return streams if isinstance(streams, list) else []


async def top_blocked_ip(ctx: ActionContext) -> str | None:
    """Source la plus fréquente des `waf_blocked` récents (Loki), None s'il n'y en a aucun."""
    counts: Counter[str] = Counter()
    for stream in await _loki_waf_blocked(ctx, LOKI_WAF_BLOCKED, LOKI_SCAN_LIMIT):
        for entry in stream.get("values", []) if isinstance(stream, dict) else []:
            try:
                ip = str(_canonical_ip(str(json.loads(entry[1]).get("client_ip", ""))))
            except (ValueError, TypeError, IndexError, KeyError, AttributeError):
                continue  # ligne non JSON / IP absente ou malformée : ignorée
            counts[ip] += 1
    return counts.most_common(1)[0][0] if counts else None


async def resolve_target(params: dict[str, Any], ctx: ActionContext) -> str:
    source = params.get("source", "from_event")
    if source not in LOKI_SOURCES:
        return resolve_source_ip(params, ctx)
    if source == "from_event_or_loki" and _event_ip(ctx):
        return guard_ip(_event_ip(ctx), ctx)  # IP désignée par le detector : prioritaire (contrat §3)
    ip = await top_blocked_ip(ctx)
    if ip is None:
        raise ActionError(f"aucun événement waf_blocked dans les {LOKI_WINDOW_S}s : source introuvable")
    return guard_ip(ip, ctx)


def guard_ip_or_reason(raw: object, ctx: ActionContext) -> str:
    try:
        return guard_ip(raw, ctx)
    except (ActionError, ValueError) as exc:
        return f"<non résolue : {exc}>"


class _WafDeny(Action):
    deny_list: str  # temporary | permanent

    @classmethod
    def check_params(cls, params: dict[str, Any]) -> None:
        _check_source(params)

    async def plan(self, ctx: ActionContext) -> str:
        source = self.params.get("source")
        if source == "from_event_or_loki" and _event_ip(ctx):
            target = guard_ip_or_reason(_event_ip(ctx), ctx)
        elif source in LOKI_SOURCES:
            target = "la source la plus fréquente des waf_blocked récents (Loki)"
        else:
            try:
                target = resolve_source_ip(self.params, ctx)
            except ActionError as exc:
                target = f"<non résolue : {exc}>"
        return f"ajouterait {target} à la liste de deny WAF ({self.deny_list}) puis recharger Nginx"

    async def execute(self, ctx: ActionContext) -> ActionResult:
        ip = await resolve_target(self.params, ctx)
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
    """Lecture seule : le WAF a-t-il bien bloqué (événement `waf_blocked` dans Loki) ?

    `require: true` : l'absence de tout blocage observé est un ÉCHEC de l'action (aucune preuve que
    l'attaque soit contenue -> pas de clôture sur cette action, nouvelle tentative puis escalade)."""

    type = "confirm_waf_block"
    mutating = False

    @classmethod
    def check_params(cls, params: dict[str, Any]) -> None:
        if not isinstance(params.get("require", False), bool):
            raise ActionParamError("param 'require' : booléen")

    async def plan(self, ctx: ActionContext) -> str:
        return "vérifierait la présence d'événements waf_blocked récents dans Loki"

    async def execute(self, ctx: ActionContext) -> ActionResult:
        query = LOKI_WAF_BLOCKED
        if ctx.event and ctx.event.source_ip:
            query += f' |= "{ctx.event.source_ip}"'  # IP validée (ipaddress) -> pas d'injection LogQL
        streams = await _loki_waf_blocked(ctx, query, 1)
        confirmed = any(isinstance(s, dict) and s.get("values") for s in streams)
        if not confirmed and self.params.get("require", False):
            raise ActionError(f"aucun blocage WAF observé dans les {LOKI_WINDOW_S}s : attaque non contenue")
        return ActionResult(ok=True, data={"confirmed": confirmed},
                            detail="blocage WAF confirmé" if confirmed else "aucun blocage WAF récent observé")
