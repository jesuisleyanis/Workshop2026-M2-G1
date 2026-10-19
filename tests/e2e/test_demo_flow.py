"""Tests end-to-end de la chaîne Zero-Touch Recovery.

Rejouent les 5 temps de la démo contre une stack RÉELLE levée (`make up`).
Sautés automatiquement si la stack n'est pas joignable — ils ne cassent pas la
suite unitaire. Lancer explicitement :

    make up && make seed
    RESILIENCE_E2E=1 pytest tests/e2e -q

Chaque scénario d'attacks/scenarios vérifie le contrat :
  avant (verify_tx OK) -> attaque -> détection -> remédiation -> après (verify_tx OK).

Preuve de la reprise *autonome* :
  - data_corruption : verify_tx passe KO après l'injection PUIS repasse OK seul
    (preuve forte : la remédiation restore_pg_dump a bien agi).
  - scénarios réseau : le service reste/redevient utilisable après l'attaque bornée ;
    si le moteur de remédiation est joignable (REMEDIATION_BASE + REMEDIATION_TOKEN),
    on vérifie EN PLUS qu'un incident du bon type a été clos (status "closed").
"""
from __future__ import annotations

import json
import os
import ssl
import subprocess
import time
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BASE_URL = os.environ.get("BASE_URL", "https://localhost")

# API interne du moteur de remédiation (non exposée sur edge). Optionnelle :
# renseigner pour la preuve "incident clos". Ex : REMEDIATION_BASE=http://localhost:8005
REMEDIATION_BASE = os.environ.get("REMEDIATION_BASE")
REMEDIATION_TOKEN = os.environ.get("REMEDIATION_TOKEN")

_CTX = ssl.create_default_context()
_CTX.check_hostname = False
_CTX.verify_mode = ssl.CERT_NONE

# scénario -> incident_type attendu (docs/contracts.md §3 ; aligné sur decision_table.yml)
INCIDENT_TYPE = {
    "service_flood": "service_flood",
    "auth_abuse": "auth_abuse",
    "web_attack": "web_attack",
    "data_corruption": "data_corruption",
}

RECOVERY_TIMEOUT_S = 60
POLL_S = 5

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
    """Transaction de contrôle (scripts/verify_tx). 0 = service utilisable."""
    return subprocess.run(
        [str(ROOT / "scripts" / "verify_tx")],
        env={**os.environ, "BASE_URL": BASE_URL},
    ).returncode


def _wait_verify_ok(timeout_s: int = RECOVERY_TIMEOUT_S) -> float | None:
    """Attend que verify_tx repasse OK. Retourne le temps de reprise (s) ou None."""
    start = time.monotonic()
    deadline = start + timeout_s
    while time.monotonic() < deadline:
        if _verify_tx() == 0:
            return time.monotonic() - start
        time.sleep(POLL_S)
    return None


def _wait_verify_ko(timeout_s: int = 30) -> bool:
    """Attend que verify_tx tombe KO (preuve que le défaut a bien eu un effet)."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if _verify_tx() != 0:
            return True
        time.sleep(2)
    return False


def _engine_configured() -> bool:
    return bool(REMEDIATION_BASE and REMEDIATION_TOKEN)


def _incident_closed(incident_type: str, timeout_s: int = RECOVERY_TIMEOUT_S) -> bool:
    """Si le moteur est joignable : un incident du type attendu est-il clos ?"""
    deadline = time.monotonic() + timeout_s
    req = urllib.request.Request(
        f"{REMEDIATION_BASE}/incidents?limit=50",
        headers={"Authorization": f"Bearer {REMEDIATION_TOKEN}"},
    )
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(req, timeout=5, context=_CTX) as resp:
                incidents = json.loads(resp.read()).get("incidents", [])
            for inc in incidents:
                if inc.get("incident_type") == incident_type and inc.get("status") == "closed":
                    return True
        except Exception:
            pass
        time.sleep(POLL_S)
    return False


def _ansible(playbook: str, *extra: str) -> int:
    """Lance un playbook côté hôte (déclencheur data_corruption / backup)."""
    cmd = [
        "ansible-playbook",
        str(ROOT / "infra" / "ansible" / "playbooks" / playbook),
        "-i", str(ROOT / "infra" / "ansible" / "inventory" / "hosts.ini"),
        "-e", f"project_root={ROOT}",
        *extra,
    ]
    return subprocess.run(cmd, timeout=120).returncode


@pytest.fixture(scope="session", autouse=True)
def require_stack():
    if not _stack_up():
        pytest.skip("stack non joignable — `make up` d'abord")


def test_avant_service_utilisable():
    assert _verify_tx() == 0, "état 'avant' doit être OK"


@pytest.mark.parametrize("scenario", ["service_flood", "auth_abuse", "web_attack"])
def test_recovery_after_network_attack(scenario):
    # avant
    assert _verify_tx() == 0, "état 'avant' doit être OK"
    # attaque bornée (depuis le profil local en dev ; depuis le PC Attaquant en démo)
    subprocess.run(
        [str(ROOT / "attacks" / "run.sh"), scenario,
         "--target", BASE_URL, "--duration", "15", "--rate", "40"],
        timeout=90,
    )
    # après : la reprise autonome doit laisser/rendre le service utilisable
    recovery = _wait_verify_ok()
    assert recovery is not None, f"la reprise autonome a échoué pour {scenario}"
    print(f"[e2e] {scenario}: service utilisable (reprise ≤ {recovery:.1f}s)")
    # preuve forte optionnelle : incident du bon type clos côté moteur
    if _engine_configured():
        assert _incident_closed(INCIDENT_TYPE[scenario]), \
            f"aucun incident '{INCIDENT_TYPE[scenario]}' clos côté remédiation"


def test_recovery_after_data_corruption():
    """Scénario de CORRECTION (≠ disponibilité) : corruption réversible de données
    fictives -> verify_tx KO -> restauration autonome -> verify_tx OK."""
    if subprocess.run(["bash", "-c", "command -v ansible-playbook"]).returncode != 0:
        pytest.skip("ansible-playbook absent — déclencheur data_corruption indisponible")

    # avant : état nominal + dump sain disponible pour la remédiation restore_pg_dump
    assert _verify_tx() == 0, "état 'avant' doit être OK"
    assert _ansible("pg_backup.yml") == 0, "création du dump sain préalable échouée"

    corrupted = False
    try:
        # injection de la corruption (côté opérateur : la base n'est pas exposée)
        assert _ansible("db_corrupt_fake.yml") == 0, "injection data_corruption échouée"
        corrupted = True
        # le défaut doit avoir un effet observable
        assert _wait_verify_ko(), "verify_tx aurait dû tomber KO après la corruption"
        # reprise autonome par restauration
        recovery = _wait_verify_ok()
        assert recovery is not None, "la restauration autonome a échoué"
        print(f"[e2e] data_corruption: données restaurées (reprise ≤ {recovery:.1f}s)")
        corrupted = False  # la remédiation a restauré : plus besoin du revert manuel
        if _engine_configured():
            assert _incident_closed("data_corruption"), \
                "aucun incident 'data_corruption' clos côté remédiation"
    finally:
        # filet de sécurité : si la remédiation n'a pas restauré, on annule nous-mêmes
        if corrupted:
            _ansible("db_corrupt_fake.yml", "-e", "mode=revert")
