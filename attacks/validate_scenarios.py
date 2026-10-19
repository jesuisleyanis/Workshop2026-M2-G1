"""Valide que chaque scénario déclare bien le contrat Red Team <-> Blue Team.

Chaque scenarios/*.yml doit porter : name, objectif, cible, signal_attendu,
incident_type (dans l'énumération figée), remediation_attendue (non vide),
critere_de_reussite. C'est ce qui garantit qu'un scénario est relié à une
détection et à une action de remédiation (docs/contracts.md §3/§4).
"""

from __future__ import annotations

from pathlib import Path

import yaml

VALID_INCIDENT_TYPES = {
    "service_flood",
    "auth_abuse",
    "web_attack",
    "data_corruption",
    "unknown",
}

REQUIRED_KEYS = (
    "name",
    "objectif",
    "cible",
    "signal_attendu",
    "incident_type",
    "remediation_attendue",
    "critere_de_reussite",
)


def validate_scenario(data: dict) -> list[str]:
    """Renvoie la liste des erreurs d'un scénario (vide = valide)."""
    errors: list[str] = []
    for key in REQUIRED_KEYS:
        if key not in data or data[key] in (None, "", [], {}):
            errors.append(f"clé obligatoire manquante ou vide : {key}")
    itype = data.get("incident_type")
    if itype is not None and itype not in VALID_INCIDENT_TYPES:
        errors.append(f"incident_type invalide : {itype}")
    rem = data.get("remediation_attendue")
    if isinstance(rem, list) and len(rem) == 0:
        errors.append("remediation_attendue vide")
    return errors


def validate_dir(scenario_dir: str | Path) -> dict[str, list[str]]:
    """Valide tous les scénarios d'un dossier. Renvoie {fichier: [erreurs]}."""
    results: dict[str, list[str]] = {}
    for path in sorted(Path(scenario_dir).glob("*.yml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        results[path.name] = validate_scenario(data)
    return results


if __name__ == "__main__":
    import sys

    here = Path(__file__).resolve().parent / "scenarios"
    results = validate_dir(here)
    ok = True
    for name, errors in results.items():
        if errors:
            ok = False
            print(f"FAIL {name}: {errors}")
        else:
            print(f"OK   {name}")
    sys.exit(0 if ok else 1)
