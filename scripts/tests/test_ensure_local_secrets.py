"""scripts/ensure-local-secrets.sh : secrets locaux du back-office facial (absents de SOPS)."""

from __future__ import annotations

import base64
import os
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


def _run_out(target: Path) -> subprocess.CompletedProcess:
    return subprocess.run([bash, SCRIPT.as_posix(), target.as_posix()], check=True, capture_output=True,
                          text=True, encoding="utf-8")


def test_env_without_trailing_newline_is_not_corrupted(tmp_path):
    # Sans \n final, la 1re ligne ajoutée serait collée à la dernière valeur (JWT_SECRET=xFACE_...).
    (tmp_path / ".env").write_bytes(b"JWT_SECRET=x")
    _run(tmp_path)
    env = _parse(tmp_path / ".env")
    assert env["JWT_SECRET"] == ["x"]
    assert all(len(env[k]) == 1 and env[k][0] for k in KEYS)


def test_crlf_empty_value_is_treated_as_missing(tmp_path):
    # `KEY=\r` (fichier CRLF) n'est pas une valeur : le secret est généré, pas recopié avec un \r.
    (tmp_path / ".env").write_bytes(b"JWT_SECRET=x\r\nFACE_DATA_KEY=\r\n")
    (tmp_path / ".env.local").write_bytes(b"FACE_INTERNAL_TOKEN=tok123\r\n")
    _run(tmp_path)
    env_text = (tmp_path / ".env").read_bytes()
    env = _parse(tmp_path / ".env")
    assert len(base64.b64decode(env["FACE_DATA_KEY"][-1])) == 32
    assert env["FACE_DATA_KEY"] == [env["FACE_DATA_KEY"][-1]], "ligne vide KEY=\r retirée"
    assert env["FACE_INTERNAL_TOKEN"] == ["tok123"], "valeur CRLF de .env.local recopiée sans \r"
    assert b"tok123\r" not in env_text


def test_mismatch_between_sops_and_local_warns_with_the_key_name_only(tmp_path):
    (tmp_path / ".env").write_text("FACE_DATA_KEY=sops-secret-value\n", encoding="utf-8")
    (tmp_path / ".env.local").write_text("FACE_DATA_KEY=local-secret-value\n", encoding="utf-8")
    out = _run_out(tmp_path)
    assert "FACE_DATA_KEY" in out.stderr and "enrôlements" in out.stderr
    for secret in ("sops-secret-value", "local-secret-value"):
        assert secret not in out.stderr and secret not in out.stdout
    assert _parse(tmp_path / ".env")["FACE_DATA_KEY"] == ["sops-secret-value"], "SOPS l'emporte"
    # Valeurs identiques : aucun avertissement.
    (tmp_path / ".env.local").write_text("FACE_DATA_KEY=sops-secret-value\n", encoding="utf-8")
    (tmp_path / ".env").write_text("FACE_DATA_KEY=sops-secret-value\n", encoding="utf-8")
    assert "ATTENTION" not in _run_out(tmp_path).stderr


def test_mqtt_bind_addr_is_carried_over_from_env_local_but_never_generated(tmp_path):
    # Absent de .env.local : rien n'est inventé (le défaut du Compose, IP du hotspot, s'applique).
    (tmp_path / ".env").write_text("JWT_SECRET=x\n", encoding="utf-8")
    _run(tmp_path)
    assert "MQTT_BIND_ADDR" not in _parse(tmp_path / ".env")
    assert "MQTT_BIND_ADDR" not in _parse(tmp_path / ".env.local")
    # Présent dans .env.local : recopié à chaque `make decrypt` (.env absent de la clé)...
    with (tmp_path / ".env.local").open("a", encoding="utf-8") as f:
        f.write("MQTT_BIND_ADDR=127.0.0.1\n")
    (tmp_path / ".env").write_text("JWT_SECRET=x\n", encoding="utf-8")
    _run(tmp_path)
    assert _parse(tmp_path / ".env")["MQTT_BIND_ADDR"] == ["127.0.0.1"]
    # ... et remplace la valeur de SOPS (secrets.example.env la fixe à l'IP du hotspot).
    (tmp_path / ".env").write_text("MQTT_BIND_ADDR=192.168.137.1\nJWT_SECRET=x\n", encoding="utf-8")
    _run(tmp_path)
    env = _parse(tmp_path / ".env")
    assert env["MQTT_BIND_ADDR"] == ["127.0.0.1"] and env["JWT_SECRET"] == ["x"]


@pytest.mark.skipif(os.name == "nt", reason="modes POSIX non significatifs sous Windows")
def test_env_is_created_private_when_absent(tmp_path):
    _run(tmp_path)
    assert (tmp_path / ".env").stat().st_mode & 0o077 == 0
    assert (tmp_path / ".env.local").stat().st_mode & 0o077 == 0
