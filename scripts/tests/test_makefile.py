"""Contrat de `make test` (ticket #19) : l'agrégat reflète l'état réel du dépôt.

Vérifiable sans `make` : on lit le Makefile et on contrôle que chaque répertoire de tests
Python du dépôt est bien couvert, qu'un process pytest est lancé par composant et qu'un
échec n'est plus avalé par un `|| echo`.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

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
        # .claude/ : worktrees locaux des sessions d'agent (copies du dépôt, jamais versionnées).
        if not tests_dir.is_dir() or any(p in rel for p in ("node_modules", ".venv", "venv/", "site-packages", ".claude/")):
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
        dirs[:] = [d for d in dirs if d not in {"node_modules", ".git", "dist", ".claude"}]
        if "package.json" not in files or Path(top) == ROOT:
            continue
        scripts = json.loads((Path(top) / "package.json").read_text(encoding="utf-8")).get("scripts", {})
        if "vitest" not in scripts.get("test", ""):
            continue
        rel = Path(top).relative_to(ROOT).as_posix()
        assert re.search(rf"(?:^|\s){re.escape(rel)}(?:\s|$)", looped), f"{rel} non couvert par make test-front"


# --------------------------------------------------------------------------- Compose et .env
def test_compose_is_defined_once_with_the_root_env_file() -> None:
    """Toute commande compose passe par $(COMPOSE), qui porte `--env-file .env` une seule fois."""
    # `=` (récursif) : `$(wildcard .env)` est évalué à l'exécution, donc APRÈS `make decrypt` ;
    # REAL_IP=1 ajoute la surcouche « IP réelle » (Caddy).
    m = re.search(r"^COMPOSE\s*:?=\s*(.*)$", MAKEFILE, re.M)
    assert m and m.group(1).startswith("docker compose -f infra/compose/docker-compose.yml ")
    assert "$(if $(wildcard .env),--env-file .env)" in m.group(1)
    lines = [line for line in MAKEFILE.splitlines() if not line.lstrip().startswith("#")]
    assert sum("docker compose" in line for line in lines) == 1, "docker compose hors de $(COMPOSE)"
    assert sum("--env-file" in line for line in lines) == 1, "--env-file redondant dans une cible"
    for target in ("up", "up-full", "up-iot", "ps", "down"):
        assert "$(COMPOSE) " in _recipe(target), f"{target} doit utiliser $(COMPOSE)"
    detector_off = re.search(r"^DETECTOR_OFF\s*=(.*)$", MAKEFILE, re.M).group(1)
    assert re.search(r"\$\(COMPOSE\)( \$\(PROFILES_\w+\))? stop detector", detector_off)
    assert re.search(r"\$\(COMPOSE\)( \$\(PROFILES_\w+\))? start detector", detector_off)
    for target in ("capture-baseline", "capture-attack"):
        assert "$(COMPOSE) exec -T collector" in _recipe(target)


def test_up_full_also_starts_the_iot_broker() -> None:
    # Décision d'équipe : `make up-full` lève aussi mosquitto (hors hotspot : MQTT_BIND_ADDR, runbook).
    assert "$(COMPOSE) $(PROFILES_FULL) --profile iot up -d --build" in _recipe("up-full")
    assert {"--profile demo", "--profile full"} <= set(re.findall(r"--profile \w+", " ".join(_var("PROFILES_FULL")) + " " + " ".join(_var("PROFILES_DEMO"))))


# --------------------------------------------------------------------------- bit exécutable
_INTERPRETERS = {"bash", "sh", ".", "source", "python", "python3", "$(PYTHON)", "$(PY_HOST)"}
_SCRIPT_PATH = r"((?:scripts|attacks|security)/[\w.-]+(?:/[\w.-]+)*)"


def _directly_invoked_scripts() -> set[str]:
    """Scripts lancés par leur chemin (pas via `bash x` / `python3 x`) par le Makefile, puis par eux."""
    todo: set[str] = set()
    for line in MAKEFILE.splitlines():
        if line.startswith("\t") or line.startswith("DETECTOR_OFF"):
            for m in re.finditer(rf"(?:(\S+)\s+)?(?<![\w/.$()-]){_SCRIPT_PATH}", line):
                if m.group(1) not in _INTERPRETERS:
                    todo.add(m.group(2))
    seen: set[str] = set()
    while todo:
        rel = todo.pop()
        # .md / .env : chemins cités dans un message ou lus par grep, jamais exécutés.
        if rel in seen or not (ROOT / rel).is_file() or rel.endswith((".md", ".env")):
            continue
        seen.add(rel)
        for line in (ROOT / rel).read_text(encoding="utf-8").splitlines():
            if line.lstrip().startswith("#"):
                continue
            for m in re.finditer(rf'(\S*)\s*"\$\{{ROOT\}}/{_SCRIPT_PATH}"', line):
                prefix = m.group(1)  # interpréteur, affectation (VAR=) ou redirection : pas une exécution
                if prefix not in _INTERPRETERS and not prefix.endswith("=") and not prefix.startswith((">", "<")):
                    todo.add(m.group(2))
    return seen


@pytest.mark.skipif(shutil.which("git") is None, reason="git requis")
def test_directly_invoked_scripts_are_executable_in_git() -> None:
    """Un script lancé par son chemin doit être en 100755 dans l'index git (sinon « Permission denied »)."""
    scripts = _directly_invoked_scripts()
    assert {"scripts/decrypt-secrets.sh", "attacks/run.sh", "attacks/reset.sh", "scripts/verify_tx",
            "scripts/demo.sh", "security/hardening/audit.sh", "scripts/package_deliverables.sh"} <= scripts
    out = subprocess.run(["git", "ls-files", "-s", "--", *sorted(scripts), "scripts/ensure-local-secrets.sh"],
                         cwd=ROOT, capture_output=True, text=True, check=False)
    if out.returncode != 0:
        pytest.skip("pas un dépôt git")
    modes = {line.split("\t")[1]: line.split()[0] for line in out.stdout.splitlines()}
    assert scripts <= set(modes), f"scripts non suivis par git : {sorted(scripts - set(modes))}"
    assert {path: mode for path, mode in modes.items() if mode != "100755"} == {}
    # ensure-local-secrets.sh : exécutable ET appelé via bash (robuste à core.fileMode=false).
    decrypt = (ROOT / "scripts" / "decrypt-secrets.sh").read_text(encoding="utf-8")
    assert 'bash "${ROOT}/scripts/ensure-local-secrets.sh" "${ROOT}"' in decrypt
