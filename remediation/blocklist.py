"""Liste noire du WAF : lecture (carte « IP bloquées » du dashboard), déblocage et expiration.

Source de vérité : la deny-list réellement appliquée par le WAF (fichier partagé `waf-deny`, une ligne
`<ip> 1;` par IP, écrite par waf_deny_ip.yml). Le journal du moteur l'enrichit : quand, par quel incident,
liste temporaire ou permanente. Une IP présente dans le fichier mais absente du journal (ajout manuel,
journal purgé) est quand même listée — on montre ce que le WAF bloque, pas ce que le moteur croit.

Durée de vie (REMEDIATION_WAF_BLOCK_TTL_S) : le moteur écrit `<ip> 1; # until=<epoch>` (commentaire
ignoré par nginx). Une ligne sans `until=` (ancien format, ajout manuel, TTL 0) est PERMANENTE.
`purge_expired` retire les lignes échues ; l'appelant recharge alors le WAF.
"""

from __future__ import annotations

import asyncio
import ipaddress
import re
import weakref
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_UNTIL = re.compile(r"\buntil=(\d+)\b")
# Un verrou par boucle asyncio et par fichier : purge, écriture (playbook) et déblocage ne s'entrelacent
# jamais (sinon une purge pourrait réécrire le fichier par-dessus une IP tout juste ajoutée).
_LOCKS: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, dict[str, asyncio.Lock]] = (
    weakref.WeakKeyDictionary()
)


def deny_lock(path: str | Path) -> asyncio.Lock:
    """Verrou d'écriture de la deny-list (à prendre autour de toute lecture-modification-écriture)."""
    per_loop = _LOCKS.setdefault(asyncio.get_running_loop(), {})
    return per_loop.setdefault(str(path), asyncio.Lock())

_LIST_OF_ACTION = {"waf_block_ip": "temporary", "waf_blacklist_ip": "permanent"}


def _ip(token: str) -> str | None:
    """Forme canonique d'une IP littérale ; l'IPv4-mappée (``::ffff:a.b.c.d``) est repliée sur son IPv4
    (même règle que actions/waf.py) : rendu stable quelle que soit la version de Python, et un déblocage
    de ``10.0.0.7`` retire aussi la ligne ``::ffff:10.0.0.7``."""
    try:
        addr = ipaddress.ip_address(token.strip())
    except ValueError:
        return None
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
        return str(addr.ipv4_mapped)
    return str(addr)


def _line_ip(line: str) -> str | None:
    head = line.split("#", 1)[0].strip()
    return _ip(head.split()[0]) if head else None


def _line_until(line: str) -> int | None:
    """Échéance (epoch, s) d'une ligne de la deny-list ; None = permanente (pas de `until=`)."""
    _, _, comment = line.partition("#")
    m = _UNTIL.search(comment)
    return int(m.group(1)) if m else None


def read_deny_entries(path: str | Path) -> list[tuple[str, int | None]]:
    """(IP, échéance epoch ou None) de la deny-list, ordre du fichier, sans doublon."""
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return []
    out: dict[str, int | None] = {}
    for line in lines:
        ip = _line_ip(line)
        if ip and ip not in out:
            out[ip] = _line_until(line)
    return list(out.items())


def read_deny_file(path: str | Path) -> list[str]:
    """IP de la deny-list (ordre du fichier, sans doublon) ; lignes invalides ou commentées ignorées."""
    return [ip for ip, _ in read_deny_entries(path)]


def _atomic_write(p: Path, content: str) -> None:
    """Fichier temporaire + rename dans le même répertoire : le WAF ne relit jamais un fichier partiel."""
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(p)


def purge_expired(path: str | Path, now: float) -> list[str]:
    """Retire les lignes dont l'échéance `until` est passée ; renvoie les IP retirées.

    Les lignes sans échéance (permanentes, ancien format), les commentaires et les autres IP sont
    conservés tels quels. Aucune écriture si rien n'a expiré.
    """
    p = Path(path)
    try:
        lines = p.read_text(encoding="utf-8").splitlines(keepends=True)
    except FileNotFoundError:
        return []
    kept, removed = [], []
    for line in lines:
        until, ip = _line_until(line), _line_ip(line)
        if ip and until is not None and until <= now:
            removed.append(ip)
        else:
            kept.append(line)
    if removed:
        _atomic_write(p, "".join(kept))
    return removed


def list_blocked_ips(deny_file: str | Path, blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """IP bloquées + contexte du journal (`blocks` : blocages réussis, le plus récent d'abord)."""
    latest: dict[str, dict[str, Any]] = {}
    for b in blocks:
        ip = _ip(str(b.get("detail", "")).split(" ", 1)[0])  # detail : « <ip> bloquée (...) »
        if ip and ip not in latest:
            latest[ip] = b
    out = []
    for ip, until in read_deny_entries(deny_file):
        b = latest.get(ip, {})
        out.append({
            "ip": ip,
            "blocked_at": b.get("ts"),
            # Échéance du blocage (ISO 8601 UTC), None = permanent (TTL 0 ou ligne sans échéance).
            "expires_at": None if until is None else datetime.fromtimestamp(until, UTC)
            .isoformat(timespec="seconds").replace("+00:00", "Z"),
            "list": _LIST_OF_ACTION.get(b.get("action_type", ""), "unknown"),
            "incident_id": b.get("incident_id"),
            "incident_type": b.get("incident_type"),
        })
    out.sort(key=lambda e: e["blocked_at"] or "", reverse=True)
    return out


def remove_ip(path: str | Path, ip: str) -> bool:
    """Retire `ip` de la deny-list (déblocage par l'opérateur). True si elle y figurait.

    Écriture atomique (fichier temporaire + rename dans le même répertoire) : le WAF ne relit jamais
    un fichier à moitié écrit. Commentaires et autres IP conservés tels quels.
    """
    target = _ip(ip)
    if target is None:
        raise ValueError(f"IP invalide : {ip!r}")
    p = Path(path)
    try:
        lines = p.read_text(encoding="utf-8").splitlines(keepends=True)
    except FileNotFoundError:
        return False
    kept = [ln for ln in lines if _line_ip(ln) != target]
    if len(kept) == len(lines):
        return False
    _atomic_write(p, "".join(kept))
    return True
