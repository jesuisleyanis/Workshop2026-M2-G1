"""Interface commune des actions de remédiation.

Une action = un `type`, des `params` (venant UNIQUEMENT de la table de décision, jamais
de l'événement), une exécution idempotente et un résultat succès/échec. La métrique
`remediation_actions_total{action,result}`, la journalisation et la gestion du dry-run
sont faites par le moteur (engine.py) : une action ne fait que son travail.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, ClassVar

if TYPE_CHECKING:  # pragma: no cover
    import httpx

    from actions.blocklist import BlocklistPort
    from actions.docker_proxy import DockerProxy
    from actions.runner import AnsibleRunnerPort
    from config import Settings
    from models import IncomingEvent


class ActionError(RuntimeError):
    """Échec d'exécution métier (message sûr, sans secret)."""


class ActionParamError(ValueError):
    """Paramètres invalides dans la table de décision (détecté au chargement)."""


@dataclass
class ActionResult:
    ok: bool
    detail: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    dry_run: bool = False
    changed: bool | None = None  # False = no-op idempotent (état déjà conforme)


@dataclass
class ActionContext:
    settings: "Settings"
    http: "httpx.AsyncClient"
    docker: "DockerProxy"
    runner: "AnsibleRunnerPort"
    log: logging.Logger
    event: "IncomingEvent | None"
    incident_id: str
    dry_run: bool = False
    extra: dict[str, Any] = field(default_factory=dict)
    blocklist: "BlocklistPort | None" = None  # écriture de la liste de blocage du WAF


class Action(ABC):
    type: ClassVar[str]
    # mutating=True : modifie l'état du SI -> bloqué en dry-run, et suivi d'une vérification.
    mutating: ClassVar[bool] = True

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        self.params: dict[str, Any] = dict(params or {})
        self.check_params(self.params)

    @classmethod
    def check_params(cls, params: dict[str, Any]) -> None:
        """Valide les paramètres (appelé au chargement de la table ET à l'exécution)."""

    @abstractmethod
    async def execute(self, ctx: ActionContext) -> ActionResult:
        """Exécute l'action. Doit être idempotente (rejouable sans effet de bord cumulatif)."""

    async def plan(self, ctx: ActionContext) -> str:
        """Description de ce qui SERAIT fait (dry-run). Ne doit rien modifier."""
        return f"{self.type} params={self.params}"
