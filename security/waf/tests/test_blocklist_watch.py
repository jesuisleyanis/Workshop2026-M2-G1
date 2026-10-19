"""98-blocklist-watch.sh : le WAF se recharge seul quand le moteur modifie la liste de blocage.

Le moteur n'a aucun moyen de joindre le WAF (ni docker exec, ni signal) : tout repose sur ce
script. On le teste avec un faux `nginx` qui enregistre ses appels ; le comportement avec le
vrai nginx est dans test_waf_image.py (opt-in, Docker).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

WATCH = Path(__file__).resolve().parents[1] / "docker-entrypoint.d" / "98-blocklist-watch.sh"

pytestmark = pytest.mark.skipif(shutil.which("sh") is None, reason="sh absent")

FAKE_NGINX = """#!/bin/sh
echo "$@" >> "$FAKE_NGINX_LOG"
if [ "$1" = "-t" ] && [ -f "$FAKE_NGINX_BROKEN" ]; then exit 1; fi
exit 0
"""


@pytest.fixture
def box(tmp_path):
    bindir, listdir = tmp_path / "bin", tmp_path / "blocklist"
    bindir.mkdir()
    listdir.mkdir()
    nginx = bindir / "nginx"
    nginx.write_text(FAKE_NGINX, encoding="utf-8", newline="\n")
    nginx.chmod(0o755)
    env = {
        "PATH": f"{bindir.as_posix()}{os.pathsep}{os.environ['PATH']}",
        "BLOCKLIST_DIR": listdir.as_posix(),
        "BLOCKLIST_WATCH_STATE": (tmp_path / "state").as_posix(),
        "FAKE_NGINX_LOG": (tmp_path / "nginx.log").as_posix(),
        "FAKE_NGINX_BROKEN": (tmp_path / "broken").as_posix(),
    }

    class Box:
        dir = listdir
        broken = tmp_path / "broken"

        @staticmethod
        def run(*args):
            return subprocess.run(["sh", WATCH.as_posix(), *args], env=env, capture_output=True, text=True, timeout=30)

        @staticmethod
        def calls() -> list[str]:
            log = tmp_path / "nginx.log"
            return log.read_text(encoding="utf-8").splitlines() if log.exists() else []

        @staticmethod
        def write(text: str, name: str = "blocked_ips.conf") -> None:
            tmp = listdir / f".{name}.tmp"
            tmp.write_text(text, encoding="utf-8", newline="\n")
            os.replace(tmp, listdir / name)               # comme le moteur : renommage atomique

    return Box


def test_first_check_reloads_nothing_to_compare_then_reloads_on_change(box):
    box.write("# vide\n")
    # état initial inconnu : le 1er contrôle voit une empreinte différente de « rien » et recharge
    assert box.run("--once").returncode == 0
    assert box.calls() == ["-t", "-s reload"]
    assert box.run("--once").returncode == 0
    assert box.calls() == ["-t", "-s reload"]               # inchangé : aucun appel de plus


def test_change_by_rename_triggers_test_then_reload_in_that_order(box):
    box.write("# vide\n")
    box.run("--once")
    box.write("203.0.113.7 1; # list=permanent incident=x\n")
    assert box.run("--once").returncode == 0
    assert box.calls()[2:] == ["-t", "-s reload"]


def test_invalid_list_is_never_loaded_and_not_retried_until_it_changes(box):
    box.write("# vide\n")
    box.run("--once")
    before = box.calls()
    box.broken.write_text("x", encoding="utf-8")            # nginx -t échoue
    box.write("ligne mal formée\n")
    res = box.run("--once")
    assert res.returncode == 1 and "invalide" in res.stderr
    assert box.calls() == before + ["-t"]                    # testé, jamais rechargé
    assert box.run("--once").returncode == 0                 # même contenu : pas de nouveau test ni de spam
    assert box.calls() == before + ["-t"]
    box.broken.unlink()
    box.write("203.0.113.7 1;\n")                            # corrigé -> rechargé
    assert box.run("--once").returncode == 0
    assert box.calls()[-2:] == ["-t", "-s reload"]


def test_any_conf_file_of_the_directory_counts(box):
    """Le `include` nginx est un glob : un autre fichier *.conf du dossier doit aussi recharger."""
    box.write("# vide\n")
    box.run("--once")
    box.write("198.51.100.9 1;\n", name="manual.conf")
    assert box.run("--once").returncode == 0
    assert box.calls()[-2:] == ["-t", "-s reload"]


def test_empty_directory_is_a_stable_state(box):
    assert box.run("--once").returncode == 0                 # aucun fichier : pas de crash
    n = len(box.calls())
    assert box.run("--once").returncode == 0 and len(box.calls()) == n


import sys  # noqa: E402


@pytest.mark.skipif(sys.platform == "win32", reason="MSYS tue les tâches de fond à la sortie du shell ; couvert sur la vraie image (test_waf_image.py)")
def test_launcher_returns_immediately_and_detaches(box, tmp_path):
    """Sans argument (entrypoint de l'image) : rend la main tout de suite, la boucle tourne en fond
    et reload quand le fichier change. Sorties vers des fichiers : un tube resterait ouvert par la
    boucle de fond (comme stderr du conteneur, ici sans importance) et bloquerait subprocess."""
    env = {**os.environ, "PATH": f"{(tmp_path / 'bin').as_posix()}{os.pathsep}{os.environ['PATH']}",
           "BLOCKLIST_DIR": box.dir.as_posix(), "BLOCKLIST_WATCH_STATE": (tmp_path / "state").as_posix(),
           "BLOCKLIST_WATCH_INTERVAL_S": "1", "FAKE_NGINX_LOG": (tmp_path / "nginx.log").as_posix(),
           "FAKE_NGINX_BROKEN": box.broken.as_posix()}
    box.write("# vide" + chr(10))
    err = (tmp_path / "launcher.err").open("w")
    res = subprocess.run(["sh", WATCH.as_posix()], env=env, stdout=subprocess.DEVNULL, stderr=err, timeout=15)
    assert res.returncode == 0
    try:
        box.write("203.0.113.7 1;" + chr(10))
        deadline = time.time() + 15
        while time.time() < deadline and box.calls()[-2:] != ["-t", "-s reload"]:
            time.sleep(0.3)
        assert box.calls()[-2:] == ["-t", "-s reload"]
    finally:
        subprocess.run(["sh", "-c", "pkill -f 98-blocklist-watch.sh || true"], capture_output=True)
        err.close()
