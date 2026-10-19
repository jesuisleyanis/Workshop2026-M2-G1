"""Tests end-to-end de la chaîne Zero-Touch Recovery.

Rejouent les 5 temps de la démo contre une stack RÉELLE levée (`make up`).
Sautés automatiquement si la stack n'est pas joignable — ils ne cassent pas la
suite unitaire. Lancer explicitement : RESILIENCE_E2E=1 pytest tests/e2e -q

Chaque scénario d'attacks/scenarios vérifie le contrat :
  avant (verify_tx OK) -> attaque -> détection -> remédiation -> après (verify_tx OK).
"""
from __future__ import annotations

import json
import os
import ssl
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BASE_URL = os.environ.get("BASE_URL", "https://localhost")
# Sous Windows, ni run.sh ni verify_tx ne sont exécutables directement (pas de shebang) : on les
# lance via bash / l'interpréteur courant.
BASH = shutil.which("bash") or "bash"
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
    return subprocess.run([sys.executable, str(ROOT / "scripts" / "verify_tx")], env={**os.environ, "BASE_URL": BASE_URL}).returncode


@pytest.fixture(scope="session", autouse=True)
def require_stack():
    if not _stack_up():
        pytest.skip("stack non joignable — `make up` d'abord")


def test_avant_service_utilisable():
    assert _verify_tx() == 0, "état 'avant' doit être OK"


# web_attack a son propre test ci-dessous : une fois la source bloquée, le verify_tx lancé depuis cet
# hôte (même IP que l'attaquant) serait lui aussi refusé -> la preuve de reprise se lit côté moteur.
@pytest.mark.parametrize("scenario", ["service_flood", "auth_abuse"])
def test_recovery_after_attack(scenario):
    # avant
    assert _verify_tx() == 0
    # attaque (bornée)
    subprocess.run(
        [BASH, str(ROOT / "attacks" / "run.sh"), scenario, "--target", BASE_URL, "--duration", "15", "--rate", "40"],
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


# --------------------------------------------------------------------------- web_attack
BLOCKLIST = ROOT / "security" / "waf" / "blocklist" / "blocked_ips.conf"
COMPOSE = ["docker", "compose", "-f", str(ROOT / "infra" / "compose" / "docker-compose.yml")]


def _status(path: str = "/") -> int:
    try:
        return urllib.request.urlopen(f"{BASE_URL}{path}", timeout=5, context=_CTX).status
    except urllib.error.HTTPError as err:
        return err.code


def _wait_status(expected: int, timeout_s: float) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if _status() == expected:
            return True
        time.sleep(1)
    return False


def _clear_blocklist() -> None:
    """Remplace la liste par renommage (comme le moteur) : le WAF se recharge seul."""
    tmp = BLOCKLIST.with_name(".blocked_ips.conf.tmp")
    tmp.write_text("# vidé par les tests e2e" + chr(10), encoding="utf-8", newline=chr(10))
    os.replace(tmp, BLOCKLIST)


def _blocked_ips() -> list[str]:
    return [line.split()[0] for line in BLOCKLIST.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")]


def _remediation_get(path: str) -> dict:
    """Interroge l'API du moteur DEPUIS son conteneur (jamais exposée sur edge), avec son token."""
    code = ("import json,os,urllib.request as u;"
            f"r=u.Request('http://127.0.0.1:8005{path}',headers={{'Authorization':'Bearer '+os.environ['REMEDIATION_TOKEN']}});"
            "print(u.urlopen(r,timeout=10).read().decode())")
    out = subprocess.run([*COMPOSE, "exec", "-T", "remediation", "python", "-c", code],
                         capture_output=True, text=True, timeout=60, check=True).stdout
    return json.loads(out)


@pytest.fixture
def clean_blocklist():
    """Liste vide avant ET après : sinon le test se bloquerait lui-même (même IP que l'attaquant)."""
    _clear_blocklist()
    assert _wait_status(200, 30), "le WAF ne répond pas 200 avec une liste vide"
    yield
    _clear_blocklist()
    subprocess.run([BASH, str(ROOT / "attacks" / "run.sh"), "--stop"], timeout=30)


def test_web_attack_blocks_the_attacker_source(clean_blocklist):
    """Chaîne complète sans humain : charges CRS -> 403 comptés -> detector (web_attack) ->
    moteur : confirm_waf_block puis waf_blacklist_ip(from_loki) -> liste écrite -> le WAF se
    recharge seul -> la source reçoit 403 -> vérification de reprise OK côté moteur."""
    before = {i["incident_id"] for i in _remediation_get("/incidents?limit=500")["incidents"]}
    subprocess.run([BASH, str(ROOT / "attacks" / "run.sh"), "web_attack", "--target", BASE_URL,
                    "--duration", "20", "--rate", "20"], timeout=90)

    assert _wait_status(403, 150), "la source attaquante n'a pas été bloquée par la remédiation"
    assert _blocked_ips(), "aucune IP dans la liste de blocage alors que le WAF refuse la source"

    incidents = [i for i in _remediation_get("/incidents?limit=500")["incidents"]
                 if i["incident_id"] not in before and i["incident_type"] == "web_attack"]
    assert incidents, "aucun incident web_attack dans le journal du moteur"
    detail = _remediation_get(f"/incidents/{incidents[0]['incident_id']}")
    results = {a["type"]: a["result"] for a in detail["actions"]}
    assert results.get("confirm_waf_block") == "success" and results.get("waf_blacklist_ip") == "success", results
    assert detail["status"] == "closed", detail["status"]   # vérification de reprise (verify_tx) passée

    # retour arrière documenté : liste vidée -> la source est de nouveau servie
    _clear_blocklist()
    assert _wait_status(200, 30)
    assert _verify_tx() == 0
