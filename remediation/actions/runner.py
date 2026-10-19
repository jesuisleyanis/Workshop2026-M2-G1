"""Port d'exécution Ansible (ansible-runner) — mockable en test.

Seuls des playbooks NOMMÉS ici peuvent être lancés : ni le nom du playbook ni ses
variables ne viennent de l'événement entrant (pas d'exécution arbitraire).

Modèle d'exécution : les playbooks tournent DANS le conteneur du moteur (`hosts: localhost`,
connexion locale), jamais sur l'hôte et jamais via `docker exec`. Ils sont copiés au build
depuis infra/ansible/playbooks/remediation/ vers `ANSIBLE_PROJECT_DIR` (lecture seule) ;
ansible-runner écrit ses artefacts dans `ANSIBLE_PRIVATE_DATA_DIR` (tmpfs). Contrat :

  waf_deny_ip.yml   extravars: deny_ip, deny_list (temporary|permanent), incident_id
                    -> ajoute "<ip> 1;" dans la deny-list partagée avec le WAF (volume
                       `waf-deny`, idempotent : lineinfile). `changed=false` si déjà présente.
                       Le rechargement de Nginx est fait par l'action (SIGHUP via le proxy).
  pg_restore.yml    extravars: backup ("latest" | nom de dump), incident_id
                    -> pg_restore du dump sain (PG_BACKUP_DIR, lecture seule) vers Postgres
                       via le réseau `data`, puis contrôle local des tables restaurées.
"""

from __future__ import annotations

import asyncio
import os
import sys
from dataclasses import dataclass
from pathlib import Path
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

    def __init__(self, private_data_dir: str, project_dir: str | None = None) -> None:
        self.private_data_dir = private_data_dir
        self.project_dir = project_dir

    async def run_playbook(
        self, playbook: str, extravars: dict[str, Any], timeout: float | None = None
    ) -> RunnerResult:
        if playbook not in ALLOWED_PLAYBOOKS:
            return RunnerResult(ok=False, rc=-1, detail=f"playbook non autorisé : {playbook}")

        def _run() -> RunnerResult:
            import ansible_runner  # noqa: PLC0415 — lourd, chargé seulement si utilisé

            os.makedirs(self.private_data_dir, exist_ok=True)  # tmpfs vide au démarrage du conteneur
            # ansible-playbook du même environnement Python que le moteur (venv de l'image).
            path = f"{Path(sys.executable).parent}{os.pathsep}{os.environ.get('PATH', '')}"
            r = ansible_runner.run(
                private_data_dir=self.private_data_dir,
                project_dir=self.project_dir,
                playbook=playbook,
                extravars=extravars,
                envvars={"PATH": path},
                quiet=True,
                rotate_artifacts=5,  # tmpfs : ne pas accumuler les artefacts
                timeout=int(timeout) if timeout else None,
            )
            stats = getattr(r, "stats", None) or {}
            changed = sum((stats.get("changed") or {}).values()) > 0 if stats else None
            ok = r.status == "successful" and r.rc == 0
            return RunnerResult(ok=ok, rc=r.rc or 0, changed=changed, detail=f"status={r.status}")

        return await asyncio.to_thread(_run)
