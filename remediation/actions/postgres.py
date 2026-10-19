"""restore_pg_dump : correction de CORRUPTION de données (≠ restauration de disponibilité)."""

from __future__ import annotations

import re
from typing import Any

from actions.base import Action, ActionContext, ActionError, ActionParamError, ActionResult
from actions.runner import PLAYBOOK_PG_RESTORE

_BACKUP_RX = re.compile(r"^(latest|[A-Za-z0-9][A-Za-z0-9_.-]{0,100})$")  # pas de '/' : pas de path traversal


class RestorePgDump(Action):
    type = "restore_pg_dump"

    @classmethod
    def check_params(cls, params: dict[str, Any]) -> None:
        backup = params.get("backup", "latest")
        if not isinstance(backup, str) or not _BACKUP_RX.match(backup) or ".." in backup:
            raise ActionParamError("param 'backup' : 'latest' ou un nom de dump simple")

    async def plan(self, ctx: ActionContext) -> str:
        return f"restaurerait le dump Postgres {self.params.get('backup', 'latest')!r} (pg_restore)"

    async def execute(self, ctx: ActionContext) -> ActionResult:
        backup = self.params.get("backup", "latest")
        res = await ctx.runner.run_playbook(
            PLAYBOOK_PG_RESTORE,
            {"backup": backup, "incident_id": ctx.incident_id},
            timeout=ctx.settings.action_timeout_s,
        )
        if not res.ok:
            raise ActionError(f"playbook {PLAYBOOK_PG_RESTORE} en échec ({res.detail or res.rc})")
        # Idempotent : restaurer deux fois le même dump aboutit au même état de données.
        return ActionResult(ok=True, detail=f"dump {backup!r} restauré", data={"backup": backup})
