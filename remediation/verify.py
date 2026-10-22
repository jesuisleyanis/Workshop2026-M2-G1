"""Exécution du script de vérification scripts/verify_tx (contrat : exit 0 = OK, 1 = KO)."""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal
from dataclasses import dataclass
from typing import Protocol


@dataclass
class VerifyResult:
    ok: bool
    rc: int | None
    detail: str = ""


class Verifier(Protocol):
    async def run(self) -> VerifyResult: ...


class ScriptVerifier:
    """Lance verify_tx SANS shell (pas d'interprétation de chaîne) avec timeout."""

    def __init__(self, path: str, timeout_s: float = 30.0) -> None:
        self.path = path
        self.timeout_s = timeout_s

    async def run(self) -> VerifyResult:
        try:
            proc = await asyncio.create_subprocess_exec(
                self.path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                start_new_session=True,  # groupe de processus dédié : le timeout tue aussi les enfants
            )
        except OSError as exc:
            return VerifyResult(ok=False, rc=None, detail=f"verify_tx non exécutable ({type(exc).__name__})")
        try:
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=self.timeout_s)
        except TimeoutError:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(proc.pid, signal.SIGKILL)
            await proc.wait()
            return VerifyResult(ok=False, rc=None, detail=f"verify_tx timeout ({self.timeout_s}s)")
        tail = out.decode("utf-8", "replace").strip().splitlines()[-1:] or [""]
        return VerifyResult(ok=proc.returncode == 0, rc=proc.returncode, detail=tail[0][:200])
