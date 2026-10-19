"""Tests end-to-end de la chaîne Zero-Touch Recovery.

Rejouent les 5 temps de la démo contre une stack RÉELLE levée (`make up`).
Sautés automatiquement si la stack n'est pas joignable — ils ne cassent pas la
suite unitaire. Lancer explicitement : RESILIENCE_E2E=1 pytest tests/e2e -q

Chaque scénario d'attacks/scenarios vérifie le contrat :
  avant (verify_tx OK) -> attaque -> détection -> remédiation -> après (verify_tx OK).
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

pytestmark = pytest.mark.skipif(
    os.environ.get("RESILIENCE_E2E") != "1",
    reason="e2e désactivés par défaut : lancer avec RESILIENCE_E2E=1 et la stack up",
)


def _stack_up() -> bool:
    try:
        req = urllib.request.Request(f"{BASE_URL}/", method="GET")
        urllib.request.urlopen(req, timeout=3, context=_CTX)
        return True
    except Exception:
        return False


def _verify_tx() -> int:
    return subprocess.run([str(ROOT / "scripts" / "verify_tx")], env={**os.environ, "BASE_URL": BASE_URL}).returncode


@pytest.fixture(scope="session", autouse=True)
def require_stack():
    if not _stack_up():
        pytest.skip("stack non joignable — `make up` d'abord")


def test_avant_service_utilisable():
    assert _verify_tx() == 0, "état 'avant' doit être OK"


@pytest.mark.parametrize("scenario", ["service_flood", "auth_abuse", "web_attack"])
def test_recovery_after_attack(scenario):
    # avant
    assert _verify_tx() == 0
    # attaque (bornée)
    subprocess.run(
        [str(ROOT / "attacks" / "run.sh"), scenario, "--target", BASE_URL, "--duration", "15", "--rate", "40"],
        timeout=60,
    )
    # après : la remédiation doit rétablir le service sans intervention humaine
    recovered = False
    for _ in range(12):
        time.sleep(5)
        if _verify_tx() == 0:
            recovered = True
            break
    assert recovered, f"la reprise autonome a échoué pour {scenario}"
