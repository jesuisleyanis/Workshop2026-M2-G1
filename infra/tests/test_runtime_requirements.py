"""Tout import tiers du code d'un service doit être une dépendance RUNTIME de son image.

Régression vécue : `auth_service/backoffice.py` importait `httpx`, déclaré seulement dans
`requirements-dev.txt` — tests verts (le venv de dev l'a), mais conteneur `auth` en boucle de
redémarrage (`ModuleNotFoundError`) et `make up` bloqué sur `dependency failed to start`.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
# Services dont l'image installe `requirements.txt` (+ libs du monorepo) puis le paquet `src/`.
SERVICES = ["services/auth", "services/payment-api", "services/face-id"]

# Nom d'import -> nom de distribution, quand ils diffèrent.
IMPORT_TO_DIST = {"jwt": "pyjwt", "sqlalchemy": "sqlalchemy", "psycopg": "psycopg"}
# Fournis par le monorepo (installés depuis libs/python/) ou transitivement par une dépendance déclarée.
PROVIDED = {
    "resilience_common",
    "resilience_db",
    "starlette",  # fastapi
    "sqlalchemy",  # resilience_db
}


def _third_party_imports(src: Path) -> set[str]:
    local = {p.name for p in src.iterdir() if p.is_dir()} | {p.stem for p in src.rglob("*.py")}
    found: set[str] = set()
    for file in src.rglob("*.py"):
        # Imports de niveau module seulement : ce sont eux qui font planter le démarrage. Les imports
        # différés dans une fonction sont des backends optionnels (ex. face-id insightface/cv2).
        for node in ast.parse(file.read_text(encoding="utf-8")).body:
            if isinstance(node, ast.Import):
                found |= {alias.name.split(".")[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                found.add(node.module.split(".")[0])
    return {
        m
        for m in found
        if m not in sys.stdlib_module_names and m not in local and m != "__future__"
    }


def _declared(requirements: Path) -> set[str]:
    names = set()
    for line in requirements.read_text(encoding="utf-8").splitlines():
        line = line.split("#")[0].strip()
        if line and not line.startswith("-"):
            names.add(re.split(r"[\[=<>~! ]", line, maxsplit=1)[0].lower().replace("_", "-"))
    return names


@pytest.mark.parametrize("service", SERVICES)
def test_every_third_party_import_is_a_runtime_requirement(service: str) -> None:
    root = ROOT / service
    declared = _declared(root / "requirements.txt")
    missing = sorted(
        module
        for module in _third_party_imports(root / "src")
        if module not in PROVIDED and IMPORT_TO_DIST.get(module, module).lower() not in declared
    )
    assert not missing, (
        f"{service}: importé par src/ mais absent de requirements.txt (runtime) : {missing}"
    )
