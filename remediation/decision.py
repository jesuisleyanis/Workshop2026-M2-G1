"""Chargement et validation de la table de décision (decision_table.yml).

Le fichier YAML fait foi : aucune règle de décision n'est codée en dur ici. Ce module ne
porte que (1) le schéma du contrat §4 et (2) des INVARIANTS DE SÉCURITÉ qui empêchent
qu'une erreur d'édition du YAML confonde les deux familles de réponse imposées par le
sujet (§2, §3.4) :

  * restauration de DISPONIBILITÉ (service_flood : bloquer / redémarrer)
  * correction de CORRUPTION / COMPROMISSION (data_corruption : restaurer le dump)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from actions import REGISTRY, ActionParamError
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from resilience_common import IncidentType

AVAILABILITY_ACTIONS = frozenset({"restart_service", "recreate_service"})
RESTORE_ACTIONS = frozenset({"restore_pg_dump"})
SUPPORTED_VERSIONS = frozenset({"1.0"})


class DecisionTableError(ValueError):
    """Table de décision invalide : le moteur refuse de démarrer (fail closed)."""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ActionSpec(_Strict):
    type: str
    params: dict[str, Any] = Field(default_factory=dict)


class Rule(_Strict):
    incident_type: IncidentType
    actions: list[ActionSpec] = Field(min_length=1)
    verify: Literal["verify_tx"]
    escalation: str


class Defaults(_Strict):
    cooldown_seconds: int = Field(ge=0)
    max_attempts: int = Field(ge=1, le=10)
    dry_run: bool


class DecisionTable(_Strict):
    version: str
    defaults: Defaults
    rules: list[Rule]

    @model_validator(mode="after")
    def _check(self) -> "DecisionTable":
        if self.version not in SUPPORTED_VERSIONS:
            raise ValueError(f"version de table non supportée : {self.version!r}")
        seen: set[IncidentType] = set()
        for rule in self.rules:
            if rule.incident_type in seen:
                raise ValueError(f"règle dupliquée pour {rule.incident_type.value}")
            seen.add(rule.incident_type)
            self._check_rule(rule)
        missing = set(IncidentType) - seen
        if missing:
            raise ValueError(f"types d'incident sans règle : {sorted(m.value for m in missing)}")
        return self

    @staticmethod
    def _check_rule(rule: Rule) -> None:
        name = rule.incident_type.value
        types = [a.type for a in rule.actions]
        for spec in rule.actions:
            cls = REGISTRY.get(spec.type)
            if cls is None:
                raise ValueError(f"[{name}] action inconnue : {spec.type!r}")
            try:
                cls.check_params(spec.params)
            except ActionParamError as exc:
                raise ValueError(f"[{name}] {spec.type}: {exc}") from exc
        if rule.escalation not in REGISTRY or REGISTRY[rule.escalation].mutating:
            raise ValueError(f"[{name}] escalation invalide : {rule.escalation!r}")
        # --- Invariants de sécurité : ne JAMAIS confondre disponibilité et corruption ---
        if rule.incident_type is IncidentType.DATA_CORRUPTION:
            if not RESTORE_ACTIONS & set(types):
                raise ValueError("[data_corruption] doit contenir restore_pg_dump")
            if AVAILABILITY_ACTIONS & set(types):
                raise ValueError("[data_corruption] ne doit PAS contenir restart/recreate (≠ disponibilité)")
        elif RESTORE_ACTIONS & set(types):
            raise ValueError(f"[{name}] restore_pg_dump est réservé à data_corruption")
        if rule.incident_type is IncidentType.UNKNOWN:
            destructive = [t for t in types if REGISTRY[t].mutating]
            if destructive:
                raise ValueError(f"[unknown] aucune action destructive autorisée : {destructive}")

    def rule_for(self, incident_type: IncidentType) -> Rule:
        """Sélection EXACTE par type : pas de repli implicite d'un type vers un autre."""
        for rule in self.rules:
            if rule.incident_type is incident_type:
                return rule
        raise DecisionTableError(f"aucune règle pour {incident_type.value}")  # inatteignable (validé)


def parse_decision_table(data: Any) -> DecisionTable:
    if not isinstance(data, dict):
        raise DecisionTableError("la table de décision doit être un mapping YAML")
    try:
        return DecisionTable.model_validate(data)
    except ValidationError as exc:
        raise DecisionTableError(str(exc)) from exc


def load_decision_table(path: str | Path) -> DecisionTable:
    try:
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))  # safe_load : pas d'objets arbitraires
    except (OSError, yaml.YAMLError) as exc:
        raise DecisionTableError(f"table illisible ({path}): {exc}") from exc
    return parse_decision_table(raw)
