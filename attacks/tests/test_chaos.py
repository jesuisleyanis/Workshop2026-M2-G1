"""Contrat statique du harnais de chaos : bornes, réversibilité, périmètre.

Ne lance pas Docker ; vérifie que chaos.sh respecte les garde-fous (liste blanche,
plafond de durée, kill-switch, pannes non destructives).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CHAOS = ROOT / "attacks" / "chaos" / "chaos.sh"


def _text() -> str:
    return CHAOS.read_text(encoding="utf-8")


def _bash_ok() -> bool:
    """Un bash fonctionnel est-il disponible ? (évite un faux échec sous WSL cassé.)"""
    try:
        return subprocess.run(["bash", "-c", "exit 0"]).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def test_chaos_script_exists_and_is_valid_bash() -> None:
    assert CHAOS.is_file()
    if not _bash_ok():
        pytest.skip("bash indisponible sur cet hôte — vérif de syntaxe sautée")
    assert subprocess.run(["bash", "-n", str(CHAOS)]).returncode == 0


def test_has_kill_switch() -> None:
    assert "--stop" in _text()
    assert "stop_all" in _text()


def test_duration_is_capped() -> None:
    # Plafond de sécurité explicite sur la durée.
    assert "DURATION > 30" in _text()


def test_scope_is_whitelisted_and_excludes_sensitive_services() -> None:
    text = _text()
    assert 'ALLOWED_SERVICES="payment-api auth front"' in text
    # Jamais la base, les secrets ou l'observabilité.
    for forbidden in ("postgres", "ollama", "grafana", "prometheus", "loki"):
        assert forbidden not in text.replace("l'observabilité", ""), (
            f"service sensible référencé : {forbidden}"
        )


def test_faults_are_non_destructive() -> None:
    text = _text().lower()
    # Réversible uniquement : pause/kill (relancé par la restart policy), jamais rm/down.
    assert "docker pause" in text and "docker unpause" in text
    assert "docker kill" in text
    for destructive in ("docker rm", "docker-compose down", "docker compose down", "volume rm"):
        assert destructive not in text, f"opération destructive interdite : {destructive}"
