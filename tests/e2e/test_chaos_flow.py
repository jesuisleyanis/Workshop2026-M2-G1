"""E2E chaos : la plateforme se rétablit d'une panne NON-ATTAQUE sans intervention.

avant (verify_tx OK) -> panne injectée (crash / freeze) -> reprise autonome
(restart policy / dégel) -> après (verify_tx OK).

Désactivé par défaut : RESILIENCE_E2E=1 et stack up requis. Nécessite Docker sur l'hôte.
"""
from __future__ import annotations

import os
import ssl
import subprocess
import time
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BASE_URL = os.environ.get("BASE_URL", "https://localhost")
_CTX = ssl.create_default_context()
_CTX.check_hostname = False
_CTX.verify_mode = ssl.CERT_NONE

RECOVERY_TIMEOUT_S = 90
POLL_S = 5

pytestmark = pytest.mark.skipif(
    os.environ.get("RESILIENCE_E2E") != "1",
    reason="e2e désactivés par défaut : lancer avec RESILIENCE_E2E=1 et la stack up",
)


def _stack_up() -> bool:
    try:
        urllib.request.urlopen(f"{BASE_URL}/", timeout=3, context=_CTX)
        return True
    except Exception:
        return False


def _verify_tx() -> int:
    return subprocess.run(
        [str(ROOT / "scripts" / "verify_tx")],
        env={**os.environ, "BASE_URL": BASE_URL},
    ).returncode


def _wait_verify_ok(timeout_s: int = RECOVERY_TIMEOUT_S) -> float | None:
    start = time.monotonic()
    while time.monotonic() - start < timeout_s:
        if _verify_tx() == 0:
            return time.monotonic() - start
        time.sleep(POLL_S)
    return None


def _chaos(fault: str, *extra: str) -> int:
    return subprocess.run(
        [str(ROOT / "attacks" / "chaos" / "chaos.sh"), fault, *extra],
        timeout=120,
    ).returncode


@pytest.fixture(scope="session", autouse=True)
def require_stack_and_docker():
    if subprocess.run(["bash", "-c", "command -v docker"]).returncode != 0:
        pytest.skip("docker absent — chaos indisponible")
    if not _stack_up():
        pytest.skip("stack non joignable — `make up` d'abord")


@pytest.mark.parametrize("fault", ["crash", "freeze"])
def test_platform_recovers_from_non_attack_fault(fault):
    # avant
    assert _verify_tx() == 0, "état 'avant' doit être OK"
    try:
        # panne bornée, réversible
        assert _chaos(fault, "--service", "payment-api", "--duration", "15") == 0
        # après : la plateforme doit redevenir utilisable seule
        recovery = _wait_verify_ok()
        assert recovery is not None, f"pas de reprise autonome après '{fault}'"
        print(f"[e2e-chaos] {fault}: service rétabli seul (≤ {recovery:.1f}s)")
    finally:
        _chaos("--stop")  # filet : dé-gèle tout conteneur resté en pause
