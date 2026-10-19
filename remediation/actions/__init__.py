"""Catalogue d'actions de remédiation (docs/contracts.md §4)."""

from __future__ import annotations

from actions.base import Action, ActionContext, ActionError, ActionParamError, ActionResult
from actions.docker import RecreateService, RestartService
from actions.ops import DryRunReport, NotifyOperator
from actions.postgres import RestorePgDump
from actions.rate_limit import TightenRateLimit
from actions.waf import ConfirmWafBlock, WafBlacklistIp, WafBlockIp

REGISTRY: dict[str, type[Action]] = {
    cls.type: cls
    for cls in (
        RestartService,
        RecreateService,
        WafBlockIp,
        WafBlacklistIp,
        TightenRateLimit,
        RestorePgDump,
        ConfirmWafBlock,
        DryRunReport,
        NotifyOperator,
    )
}


def build_action(action_type: str, params: dict | None = None) -> Action:
    try:
        cls = REGISTRY[action_type]
    except KeyError as exc:
        raise ActionParamError(f"action inconnue : {action_type!r}") from exc
    return cls(params or {})


__all__ = [
    "Action",
    "ActionContext",
    "ActionError",
    "ActionParamError",
    "ActionResult",
    "REGISTRY",
    "build_action",
]
