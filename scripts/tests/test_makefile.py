"""Contrat de `make test` (ticket #19) : l'agrégat reflète l'état réel du dépôt.

Vérifiable sans `make` : on lit le Makefile et on contrôle que chaque répertoire de tests
Python du dépôt est bien couvert, qu'un process pytest est lancé par composant et qu'un
échec n'est plus avalé par un `|| echo`.
"""

from __future__ import annotations

import json
import os
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
def test_every_vitest_app_is_covered_by_test_front() -> None:
    recipe = _recipe("test-front")
    # La boucle itère sur $(FRONT_APPS) : on l'expanse pour contrôler la liste réelle des apps.
    m = re.search(r"for app in ([^;]*);", recipe)
    assert m, "boucle `for app in ...` absente de test-front"
    looped = m.group(1).replace("$(FRONT_APPS)", " ".join(_var("FRONT_APPS")))
    for top, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in {"node_modules", ".git", "dist"}]
        if "package.json" not in files or Path(top) == ROOT:
            continue
        scripts = json.loads((Path(top) / "package.json").read_text(encoding="utf-8")).get("scripts", {})
        if "vitest" not in scripts.get("test", ""):
            continue
        rel = Path(top).relative_to(ROOT).as_posix()
        assert re.search(rf"(?:^|\s){re.escape(rel)}(?:\s|$)", looped), f"{rel} non couvert par make test-front"
