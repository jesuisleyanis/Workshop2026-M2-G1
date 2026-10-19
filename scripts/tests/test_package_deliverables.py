"""Contrat de `scripts/package_deliverables.sh` (livrable §7 Code.zip, ticket #18).

Test fonctionnel sur un faux dépôt : l'archive porte le nom exact, exclut secrets déchiffrés / clés /
dépendances / artefacts, inclut les sources, et le script ÉCHOUE si une clé privée se glisse dedans.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "package_deliverables.sh"
CODE = "Workshop2026-M2-G1-Code.zip"


def _fake_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    shutil.copy(SCRIPT, repo / "scripts" / SCRIPT.name)
    (repo / "security" / "hardening").mkdir(parents=True)
    audit = repo / "security" / "hardening" / "audit.sh"
    audit.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    audit.chmod(0o755)
    files = {
        "README.md": "# demo\n",
        "services/api/main.py": "print('x')\n",
        "security/sops/secrets.example.env": "POSTGRES_PASSWORD=change-me\n",
        ".env": "POSTGRES_PASSWORD=real\n",
        "security/sops/keys.txt": "# created\nAGE-SECRET-KEY-1QQQ\n",
        "dashboard/node_modules/x/index.js": "x",
        "dashboard/dist/index.html": "x",
        "libs/python/pkg.egg-info/PKG-INFO": "x",
        "remediation/incidents.db": "x",
        "infra/ansible/backups/dump.sql": "x",
        ".git/HEAD": "ref",
        "Workshop2026-M2-G1-Dossier.pdf": "x",
    }
    for rel, content in files.items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    return repo


def _run(repo: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", str(repo / "scripts" / SCRIPT.name)], cwd=repo, capture_output=True, text=True,
                          env={**os.environ, "LC_ALL": "C"})


@pytest.mark.skipif(shutil.which("zip") is None or shutil.which("unzip") is None, reason="zip/unzip requis")
def test_archive_has_exact_name_and_excludes_secrets_and_artifacts(tmp_path):
    repo = _fake_repo(tmp_path)
    r = _run(repo)
    assert r.returncode == 0, r.stdout + r.stderr
    archive = repo / CODE
    assert archive.is_file()
    names = set(zipfile.ZipFile(archive).namelist())
    assert {"README.md", "services/api/main.py", "security/sops/secrets.example.env", "scripts/package_deliverables.sh"} <= names
    for forbidden in (".env", "security/sops/keys.txt", ".git/HEAD", "dashboard/node_modules/x/index.js",
                      "dashboard/dist/index.html", "libs/python/pkg.egg-info/PKG-INFO", "remediation/incidents.db",
                      "infra/ansible/backups/dump.sql", "Workshop2026-M2-G1-Dossier.pdf"):
        assert forbidden not in names, f"{forbidden} ne doit pas être dans {CODE}"


@pytest.mark.skipif(shutil.which("zip") is None or shutil.which("unzip") is None, reason="zip/unzip requis")
def test_packaging_fails_if_a_private_key_slips_into_the_archive(tmp_path):
    repo = _fake_repo(tmp_path)
    (repo / "docs").mkdir()
    (repo / "docs" / "notes.md").write_text("AGE-SECRET-KEY-1ABCDEF\n", encoding="utf-8")  # pas exclu par nom
    r = _run(repo)
    assert r.returncode == 1 and "clé privée" in r.stderr
    assert not (repo / CODE).exists(), "l'archive fautive doit être supprimée"


def test_script_runs_the_hardening_audit_first():
    text = SCRIPT.read_text(encoding="utf-8")
    assert "security/hardening/audit.sh" in text and "set -euo pipefail" in text
    assert text.index("audit.sh") < text.index("zip -r")
