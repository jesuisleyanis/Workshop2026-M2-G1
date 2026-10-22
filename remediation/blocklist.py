"""Liste noire du WAF en lecture seule (carte « IP bloquées » du dashboard).

Source de vérité : la deny-list réellement appliquée par le WAF (fichier partagé `waf-deny`, une ligne
`<ip> 1;` par IP, écrite par waf_deny_ip.yml). Le journal du moteur l'enrichit : quand, par quel incident,
liste temporaire ou permanente. Une IP présente dans le fichier mais absente du journal (ajout manuel,
journal purgé) est quand même listée — on montre ce que le WAF bloque, pas ce que le moteur croit.
"""

from __future__ import annotations

import ipaddress
from pathlib import Path
from typing import Any

_LIST_OF_ACTION = {"waf_block_ip": "temporary", "waf_blacklist_ip": "permanent"}


def _ip(token: str) -> str | None:
    try:
        return str(ipaddress.ip_address(token.strip()))
    except ValueError:
        return None


def read_deny_file(path: str | Path) -> list[str]:
    """IP de la deny-list (ordre du fichier, sans doublon) ; lignes invalides ou commentées ignorées."""
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return []
    ips: list[str] = []
    for line in lines:
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        ip = _ip(line.split()[0])
        if ip and ip not in ips:
            ips.append(ip)
    return ips


def list_blocked_ips(deny_file: str | Path, blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """IP bloquées + contexte du journal (`blocks` : blocages réussis, le plus récent d'abord)."""
    latest: dict[str, dict[str, Any]] = {}
    for b in blocks:
        ip = _ip(str(b.get("detail", "")).split(" ", 1)[0])  # detail : « <ip> bloquée (...) »
        if ip and ip not in latest:
            latest[ip] = b
    out = []
    for ip in read_deny_file(deny_file):
        b = latest.get(ip, {})
        out.append({
            "ip": ip,
            "blocked_at": b.get("ts"),
            "list": _LIST_OF_ACTION.get(b.get("action_type", ""), "unknown"),
            "incident_id": b.get("incident_id"),
            "incident_type": b.get("incident_type"),
        })
    out.sort(key=lambda e: e["blocked_at"] or "", reverse=True)
    return out
