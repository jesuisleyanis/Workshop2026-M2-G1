"""Port d'exécution Ansible (ansible-runner) — mockable en test.

Seuls des playbooks NOMMÉS ici peuvent être lancés : ni le nom du playbook ni ses
variables ne viennent de l'événement entrant (pas d'exécution arbitraire).
Les playbooks vivent dans infra/ansible/playbooks et sont montés en lecture seule sous
`<ANSIBLE_PRIVATE_DATA_DIR>/project/`. Contrat attendu (à implémenter côté infra) :

  waf_deny_ip.yml   extravars: deny_ip, deny_list (temporary|permanent), incident_id
                    -> écrit l'IP dans le fichier de deny (idempotent : lineinfile)
                       puis `nginx -s reload`. `changed=false` si déjà présente.
  pg_restore.yml    extravars: backup ("latest" | nom de dump), incident_id
                    -> pg_restore du dump planifié (réseau data).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Protocol

PLAYBOOK_WAF_DENY = "waf_deny_ip.yml"
PLAYBOOK_PG_RESTORE = "pg_restore.yml"
ALLOWED_PLAYBOOKS = frozenset({PLAYBOOK_WAF_DENY, PLAYBOOK_PG_RESTORE})


@dataclass
class RunnerResult:
    ok: bool
    rc: int = 0
    changed: bool | None = None
    detail: str = ""


class AnsibleRunnerPort(Protocol):
    async def run_playbook(
        self, playbook: str, extravars: dict[str, Any], timeout: float | None = None
    ) -> RunnerResult: ...


class AnsibleRunnerAdapter:
    """Implémentation réelle basée sur ansible-runner (import paresseux)."""

    def __init__(self, private_data_dir: str) -> None:
        self.private_data_dir = private_data_dir

    async def run_playbook(
        self, playbook: str, extravars: dict[str, Any], timeout: float | None = None
    ) -> RunnerResult:
        if playbook not in ALLOWED_PLAYBOOKS:
            return RunnerResult(ok=False, rc=-1, detail=f"playbook non autorisé : {playbook}")

        def _run() -> RunnerResult:
            import ansible_runner  # noqa: PLC0415 — lourd, chargé seulement si utilisé

            r = ansible_runner.run(
                private_data_dir=self.private_data_dir,
                playbook=playbook,
                extravars=extravars,
                quiet=True,
                timeout=int(timeout) if timeout else None,
            )
            stats = getattr(r, "stats", None) or {}
            changed = sum((stats.get("changed") or {}).values()) > 0 if stats else None
            ok = r.status == "successful" and r.rc == 0
            return RunnerResult(ok=ok, rc=r.rc or 0, changed=changed, detail=f"status={r.status}")

        return await asyncio.to_thread(_run)
