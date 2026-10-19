"""Port d'écriture de la liste de blocage IP du WAF — mockable en test.

Le moteur n'a ni `docker exec`, ni accès à l'hôte (docker-socket-proxy n'autorise que quatre
appels, dont aucun ne permet de recharger nginx) : il écrit le fichier de liste dans le dossier
partagé avec le WAF, et c'est le WAF qui le surveille et se recharge
(security/waf/docker-entrypoint.d/98-blocklist-watch.sh).

Contrat avec le WAF (security/waf/templates/conf.d/default.conf.template, bloc `geo`) :
  une ligne `<ip> 1;` par source bloquée, commentaires `#` libres.

Deux garanties :
  * écriture ATOMIQUE (fichier temporaire du même dossier + `os.replace`) : nginx ne lit jamais
    un fichier à moitié écrit ;
  * le DOSSIER, pas le fichier, est monté dans le WAF : le renommage crée un nouvel inode que
    seul un montage de dossier laisse voir (voir security/waf/README.md).
"""

from __future__ import annotations

import asyncio
import ipaddress
import os
import re
import tempfile
import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timezone
from pathlib import Path
from typing import Protocol

from actions.base import ActionError

_ENTRY = re.compile(r"^\s*([0-9a-fA-F:.]+)\s+1\s*;")
_SAFE_TAG = re.compile(r"[^A-Za-z0-9._-]")
HEADER = "# Liste de blocage IP du WAF — écrite par le moteur de remédiation (actions/blocklist.py).\n"


@dataclass
class BlocklistResult:
    changed: bool  # False : l'IP était déjà dans la liste (idempotent)
    entries: int


class BlocklistPort(Protocol):
    async def add(self, ip: str, *, deny_list: str, incident_id: str) -> BlocklistResult: ...


class BlocklistFile:
    """Implémentation réelle : fichier `<ip> 1;` dans un dossier partagé avec le WAF."""

    def __init__(self, path: str | Path, max_entries: int = 1000) -> None:
        self.path = Path(path)
        self.max_entries = max_entries
        self._lock = threading.Lock()

    async def add(self, ip: str, *, deny_list: str, incident_id: str) -> BlocklistResult:
        return await asyncio.to_thread(self._add, ip, deny_list, incident_id)

    # ------------------------------------------------------------------ interne (synchrone)
    def entries(self) -> list[str]:
        try:
            text = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return []
        return [m.group(1) for line in text.splitlines() if (m := _ENTRY.match(line))]

    def _add(self, ip: str, deny_list: str, incident_id: str) -> BlocklistResult:
        # Revalidation ici aussi : ce module est la dernière barrière avant le fichier lu par nginx.
        try:
            canonical = str(ipaddress.ip_address(ip))
        except ValueError as exc:
            raise ActionError("IP invalide, refus d'écrire dans la liste de blocage") from exc
        with self._lock:
            try:
                text = self.path.read_text(encoding="utf-8")
            except FileNotFoundError:
                text = HEADER
            present = [m.group(1) for line in text.splitlines() if (m := _ENTRY.match(line))]
            if canonical in {str(ipaddress.ip_address(p)) for p in present if _valid(p)}:
                return BlocklistResult(changed=False, entries=len(present))
            if len(present) >= self.max_entries:
                raise ActionError(f"liste de blocage pleine ({self.max_entries} entrées)")
            stamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
            tag = _SAFE_TAG.sub("", f"{deny_list}")[:16]
            inc = _SAFE_TAG.sub("", incident_id)[:40]
            if text and not text.endswith("\n"):
                text += "\n"
            text += f"{canonical} 1; # list={tag} incident={inc} ts={stamp}\n"
            self._write_atomic(text)
            return BlocklistResult(changed=True, entries=len(present) + 1)

    def _write_atomic(self, text: str) -> None:
        tmp = ""
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(prefix=".blocked_ips.", suffix=".tmp", dir=self.path.parent)
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(text)
                fh.flush()
                os.fsync(fh.fileno())
            os.chmod(tmp, 0o644)  # lisible par l'utilisateur nginx du WAF (autre uid)
            os.replace(tmp, self.path)
        except OSError as exc:
            raise ActionError(f"écriture de la liste de blocage impossible ({type(exc).__name__})") from exc
        finally:
            if tmp and os.path.exists(tmp):
                os.unlink(tmp)


def _valid(value: str) -> bool:
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return False
    return True
