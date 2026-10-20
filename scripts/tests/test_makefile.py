"""Contrat de `make test` (ticket #19) : l'agrégat reflète l'état réel du dépôt.

Vérifiable sans `make` : on lit le Makefile et on contrôle que chaque répertoire de tests
Python du dépôt est bien couvert, qu'un process pytest est lancé par composant et qu'un
échec n'est plus avalé par un `|| echo`.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAKEFILE = (ROOT / "Makefile").read_text(encoding="utf-8")


def _var(name: str) -> list[str]:
    m = re.search(rf"^{name}\s*:=\s*(.*?)(?=^\S|\Z)", MAKEFILE, re.M | re.S)
    assert m, f"variable {name} absente du Makefile"
    return m.group(1).replace("\\\n", " ").split()


def _recipe(target: str) -> str:
    m = re.search(rf"^{target}:.*?\n((?:\t.*\n?)+)", MAKEFILE, re.M)
    assert m, f"cible {target} absente"
    return m.group(1)


def test_every_python_test_directory_is_covered() -> None:
    covered = set(_var("PY_COMPONENTS")) | set(_var("PY_TEST_DIRS"))
    assert "infra/tests" in covered, "infra/tests (règles SOC) omis de make test (#19)"
    # Tout répertoire `tests/` du dépôt (hors dépendances) doit être sous un chemin couvert.
    for tests_dir in ROOT.rglob("tests"):
        rel = tests_dir.relative_to(ROOT).as_posix()
        if not tests_dir.is_dir() or any(p in rel for p in ("node_modules", ".venv", "venv/", "site-packages")):
            continue
        if not any(tests_dir.glob("test_*.py")):
            continue
        assert any(rel == c or rel.startswith(c + "/") for c in covered), f"{rel} non couvert par make test"


def test_one_pytest_process_per_component_and_failures_propagate() -> None:
    recipe = _recipe("test-py")
    assert "for c in $(PY_COMPONENTS)" in recipe and "cd $$c && $(PYTHON) -m pytest" in recipe
    assert "|| echo" not in recipe, "un échec de tests ne doit pas être masqué"
    assert "exit 1" in recipe and "pipefail" in recipe
    assert re.search(r"^SHELL\s*:=\s*/bin/bash", MAKEFILE, re.M), "pipefail exige bash"


def test_face_auth_components_are_aggregated() -> None:
    """Consigne additionnelle 1 (L7-4) : face-id (pytest) et back-office (Vitest) dans `make test`."""
    assert "services/face-id" in _var("PY_COMPONENTS")
    front = _var("FRONT_APPS")
    assert "for app in $(FRONT_APPS)" in _recipe("test-front")
    # Toute app front du dépôt dotée d'un script `test` est lancée par `make test-front`.
    for pkg in [*ROOT.glob("services/*/package.json"), ROOT / "dashboard" / "package.json"]:
        if "test" in json.loads(pkg.read_text(encoding="utf-8")).get("scripts", {}):
            assert pkg.parent.relative_to(ROOT).as_posix() in front, f"{pkg.parent.name} absent de FRONT_APPS"
    assert "services/backoffice" in front
    # Exigence Node documentée (jsdom/undici) plutôt qu'un chemin d'interpréteur codé en dur.
    assert re.search(r"Node >= 22\.15", MAKEFILE)
    assert "test: test-py test-front" in MAKEFILE
