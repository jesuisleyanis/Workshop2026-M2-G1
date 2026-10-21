"""Contrat de lancement de la stack (vérifiable sans Docker).

Verrouille les points qui ont cassé le lancement (docs/plan-optimisation-lancement.md) :
- C1 : le profil `ml` (collector + detector) doit être levé par `make up*` — sans lui, pas de détection ;
- C2 : Compose doit recevoir `--env-file .env` (sinon il cherche infra/compose/.env, absent) ;
- C3 : `.dockerignore` racine = contexte léger ET contrôle anti-fuite de secrets ;
- C5 : cache pip BuildKit dans les étapes de build ;
- C6 : démarrage ordonné sur l'état *healthy* des dépendances.
"""

from __future__ import annotations

import fnmatch
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = yaml.safe_load(
    (ROOT / "infra" / "compose" / "docker-compose.yml").read_text(encoding="utf-8")
)
SERVICES = COMPOSE["services"]
MAKEFILE = (ROOT / "Makefile").read_text(encoding="utf-8")


# ---------------------------------------------------------------- Makefile
def _make_var(name: str) -> str:
    """Valeur d'une variable du Makefile, variables $(X) imbriquées résolues."""
    match = re.search(rf"^{name}\s*:?=\s*(.*)$", MAKEFILE, re.MULTILINE)
    assert match, f"variable {name} absente du Makefile"
    return re.sub(r"\$\((\w+)\)", lambda m: _make_var(m.group(1)), match.group(1))


def _target(name: str) -> tuple[list[str], str]:
    """(prérequis, recette) d'une cible du Makefile."""
    match = re.search(
        rf"^{re.escape(name)}:([^#\n]*)(?:##.*)?\n((?:\t.*\n)*)", MAKEFILE, re.MULTILINE
    )
    assert match, f"cible {name} absente du Makefile"
    return match.group(1).split(), match.group(2)


def _declared_profiles() -> set[str]:
    return {p for svc in SERVICES.values() for p in svc.get("profiles", [])}


def test_compose_receives_the_root_env_file() -> None:
    # C2 : Compose lit par défaut le .env du répertoire du fichier compose (infra/compose/).
    assert "--env-file .env" in _make_var("COMPOSE")


def test_every_launch_target_starts_the_ml_profile() -> None:
    # C1 : sans collector + detector, la démo n'a aucune détection (Zero-Touch impossible).
    assert "--profile ml" in _make_var("PROFILES_DEMO")
    for target in ("up", "up-full", "up-iot", "start", "start-full", "build"):
        _, recipe = _target(target)
        resolved = re.sub(
            r"\$\((\w+)\)",
            lambda m: _make_var(m.group(1)) if m.group(1) != "COMPOSE" else "",
            recipe,
        )
        assert "--profile ml" in resolved, f"make {target} ne lève pas le profil ml"


def test_down_and_ps_cover_every_declared_profile() -> None:
    # Un service d'un profil oublié survivrait à `make down` (ex. detector lancé à la main).
    profiles = _make_var("PROFILES_ALL")
    for profile in _declared_profiles():
        assert f"--profile {profile}" in profiles, f"PROFILES_ALL n'inclut pas le profil {profile}"
    for target in ("down", "ps"):
        assert "$(PROFILES_ALL)" in _target(target)[1], (
            f"make {target} doit couvrir tous les profils"
        )


def test_up_does_not_train_on_the_host() -> None:
    # C4 : le build du detector entraîne déjà le modèle (étape `trainer`) ; pas de sklearn requis sur le poste.
    for target in ("up", "up-full", "up-iot"):
        prereqs, _ = _target(target)
        assert "model" not in prereqs, f"make {target} ne doit plus dépendre de `model`"
        assert "check-env" in prereqs, f"make {target} doit échouer clairement sans .env"


def test_start_targets_do_not_rebuild() -> None:
    for target in ("start", "start-full"):
        assert "--build" not in _target(target)[1], f"make {target} doit relancer sans rebuild"


# ---------------------------------------------------------------- .dockerignore
DOCKERIGNORE = [
    line.strip()
    for line in (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    if line.strip() and not line.startswith("#")
]


def _ignored(path: str) -> bool:
    for pattern in DOCKERIGNORE:
        bare = pattern.removeprefix("**/")
        if (
            fnmatch.fnmatch(path, pattern)
            or fnmatch.fnmatch(path, bare)
            or path.startswith(pattern.rstrip("/") + "/")
        ):
            return True
        if pattern.startswith("**/") and any(
            fnmatch.fnmatch(part, bare) for part in path.split("/")
        ):
            return True
    return False


def _root_context_dockerfiles() -> list[Path]:
    files = []
    for svc in SERVICES.values():
        build = svc.get("build")
        if isinstance(build, dict) and build.get("context") == "../.." and "dockerfile" in build:
            files.append(ROOT / build["dockerfile"])
    return files


def test_dockerignore_blocks_secrets_and_heavy_dirs() -> None:
    for path in (
        ".env",
        ".git",
        ".venv",
        "security/sops/secrets.env",
        "x/age.key",
        "graphify-out",
        "a/node_modules",
    ):
        assert _ignored(path), f".dockerignore doit exclure {path}"


def test_dockerignore_keeps_every_build_input() -> None:
    # Ce que les Dockerfiles copient depuis la racine ne doit JAMAIS être exclu (build cassé sinon).
    dockerfiles = _root_context_dockerfiles()
    assert len(dockerfiles) >= 6
    for dockerfile in dockerfiles:
        for line in dockerfile.read_text(encoding="utf-8").splitlines():
            if not line.startswith("COPY") or "--from=" in line:
                continue
            sources = [tok for tok in line.split()[1:-1] if not tok.startswith("--")]
            for src in sources:
                assert not _ignored(src), (
                    f"{dockerfile.relative_to(ROOT)} copie {src}, exclu par .dockerignore"
                )
    # Données réelles + calibration embarquées par le build du detector.
    assert not _ignored("ml/training/data/baseline_real.csv")
    assert not _ignored("ml/training/data/calibration.json")


def test_build_stages_use_the_pip_cache_mount() -> None:
    for dockerfile in _root_context_dockerfiles():
        text = dockerfile.read_text(encoding="utf-8")
        name = dockerfile.relative_to(ROOT)
        assert "PIP_NO_CACHE_DIR" not in text, f"{name}: PIP_NO_CACHE_DIR annule le cache BuildKit"
        instructions = re.sub(
            r"\\\r?\n", " ", text
        ).splitlines()  # RUN multi-lignes -> une instruction
        for line in instructions:
            if line.startswith("RUN") and "pip install" in line:
                assert "--mount=type=cache,target=/root/.cache/pip" in line, (
                    f"{name}: pip sans cache BuildKit : {line}"
                )


# ---------------------------------------------------------------- démarrage ordonné
def test_dependencies_with_a_healthcheck_are_awaited_healthy() -> None:
    # C6 : attendre qu'une dépendance soit *healthy* (pas seulement démarrée) quand elle sait le dire.
    for name, svc in SERVICES.items():
        deps = svc.get("depends_on") or {}
        for dep in deps:
            if "healthcheck" not in SERVICES[dep]:
                continue
            assert isinstance(deps, dict), (
                f"{name}: depends_on en liste, condition de santé impossible"
            )
            assert deps[dep].get("condition") == "service_healthy", (
                f"{name} -> {dep} : service_healthy attendu"
            )
