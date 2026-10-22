"""scripts/ensure-local-secrets.sh : secrets locaux du back-office facial (absents de SOPS)."""

from __future__ import annotations

import base64
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "ensure-local-secrets.sh"
KEYS = ("FACE_INTERNAL_TOKEN", "FACE_DATA_KEY", "BACKOFFICE_BOOTSTRAP_TOKEN")

bash = shutil.which("bash")
pytestmark = pytest.mark.skipif(bash is None, reason="bash requis")


def _run(target: Path) -> None:
    subprocess.run([bash, SCRIPT.as_posix(), target.as_posix()], check=True, capture_output=True)


def _parse(path: Path) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            out.setdefault(key, []).append(value)
    return out


def test_generates_missing_secrets_once_and_keeps_them_stable(tmp_path):
    (tmp_path / ".env").write_text("JWT_SECRET=x\n", encoding="utf-8")
    _run(tmp_path)
    first = _parse(tmp_path / ".env")
    assert all(len(first[k]) == 1 and first[k][0] for k in KEYS)
    assert len(base64.b64decode(first["FACE_DATA_KEY"][0])) == 32
    assert first["BACKOFFICE_BOOTSTRAP_TOKEN"][0].startswith("init-")

    # Nouveau `make decrypt` : .env régénéré par SOPS, les secrets locaux sont réutilisés.
    (tmp_path / ".env").write_text("JWT_SECRET=x\n", encoding="utf-8")
    _run(tmp_path)
    second = _parse(tmp_path / ".env")
    assert {k: second[k] for k in KEYS} == {k: first[k] for k in KEYS}


def test_value_from_sops_wins_and_is_not_duplicated(tmp_path):
    (tmp_path / ".env").write_text("FACE_DATA_KEY=fromsops\n", encoding="utf-8")
    _run(tmp_path)
    env = _parse(tmp_path / ".env")
    assert env["FACE_DATA_KEY"] == ["fromsops"]
    assert "FACE_DATA_KEY" not in _parse(tmp_path / ".env.local")


def test_local_file_is_gitignored():
    ignored = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert ".env.local" in ignored


def test_decrypt_script_calls_it():
    assert "ensure-local-secrets.sh" in (ROOT / "scripts" / "decrypt-secrets.sh").read_text(
        encoding="utf-8"
    )
