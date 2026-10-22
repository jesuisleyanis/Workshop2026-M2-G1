"""Plan d'exécution Ansible : contrat moteur <-> playbooks de remédiation (infra/ansible/playbooks/remediation)
et exécution RÉELLE de waf_deny_ip.yml par ansible-runner, dans le modèle « localhost in-container »."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from actions.runner import (
    ALLOWED_PLAYBOOKS,
    PLAYBOOK_PG_RESTORE,
    PLAYBOOK_WAF_DENY,
    AnsibleRunnerAdapter,
)

ROOT = Path(__file__).resolve().parents[2]
PROJECT = ROOT / "infra" / "ansible" / "playbooks" / "remediation"
HOST_PLAYBOOKS = ROOT / "infra" / "ansible" / "playbooks"

# Extravars réellement passées par les actions (actions/waf.py, actions/postgres.py).
EXTRAVARS = {
    PLAYBOOK_WAF_DENY: {"deny_ip", "deny_list", "incident_id", "deny_until"},
    PLAYBOOK_PG_RESTORE: {"backup", "incident_id"},
}


def _play(name: str) -> dict:
    return yaml.safe_load((PROJECT / name).read_text(encoding="utf-8"))[0]


def test_every_allowed_playbook_exists_and_runs_locally_in_container():
    for name in ALLOWED_PLAYBOOKS:
        play = _play(name)
        assert play["hosts"] == "localhost" and play.get("connection") == "local", name
        code = "\n".join(line for line in (PROJECT / name).read_text(encoding="utf-8").splitlines()
                         if not line.lstrip().startswith("#"))
        assert "docker exec" not in code, f"{name} : jamais via docker exec"


@pytest.mark.parametrize("name", sorted(ALLOWED_PLAYBOOKS))
def test_playbook_vars_match_engine_extravars(name):
    """Chaque extravar du moteur est déclarée (défaut) par le playbook : pas de variable perdue."""
    declared = set(_play(name)["vars"])
    missing = EXTRAVARS[name] - declared
    assert not missing, f"{name} ignore les extravars {missing} passées par le moteur"


def _ansible_playbook() -> str | None:
    return shutil.which("ansible-playbook", path=str(Path(sys.executable).parent)) or shutil.which("ansible-playbook")


@pytest.mark.parametrize("playbook", sorted(p.relative_to(HOST_PLAYBOOKS) for p in HOST_PLAYBOOKS.rglob("*.yml")))
def test_playbooks_pass_syntax_check(playbook, tmp_path):
    exe = _ansible_playbook()
    if exe is None:
        pytest.skip("ansible-playbook absent")
    env = {**os.environ, "ANSIBLE_HOME": str(tmp_path), "ANSIBLE_LOCAL_TEMP": str(tmp_path / "tmp")}
    inventory = ROOT / "infra" / "ansible" / "inventory" / "hosts.ini"
    r = subprocess.run([exe, "--syntax-check", "-i", str(inventory), str(HOST_PLAYBOOKS / playbook)],
                       capture_output=True, text=True, env=env, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr


@pytest.mark.anyio
async def test_waf_deny_ip_playbook_really_writes_deny_list_idempotently(tmp_path, monkeypatch):
    pytest.importorskip("ansible_runner")
    if _ansible_playbook() is None:
        pytest.skip("ansible-playbook absent")
    deny = tmp_path / "waf-deny" / "blocked_ips.conf"
    monkeypatch.setenv("WAF_DENY_FILE", str(deny))
    monkeypatch.setenv("ANSIBLE_HOME", str(tmp_path / ".ansible"))
    monkeypatch.setenv("ANSIBLE_LOCAL_TEMP", str(tmp_path / ".ansible" / "tmp"))
    runner = AnsibleRunnerAdapter(str(tmp_path / "runner"), str(PROJECT))
    extravars = {"deny_ip": "203.0.113.77", "deny_list": "temporary", "incident_id": "inc-test"}

    first = await runner.run_playbook(PLAYBOOK_WAF_DENY, extravars, timeout=120)
    assert first.ok and first.changed is True, first
    assert deny.read_text(encoding="utf-8").splitlines() == ["203.0.113.77 1;"]

    second = await runner.run_playbook(PLAYBOOK_WAF_DENY, extravars, timeout=120)
    assert second.ok and second.changed is False, second  # idempotent : pas de doublon, pas de reload
    assert deny.read_text(encoding="utf-8").count("203.0.113.77") == 1

    bad = await runner.run_playbook(PLAYBOOK_WAF_DENY, {**extravars, "deny_ip": "1.2.3.4; evil"}, timeout=120)
    assert not bad.ok  # assert du playbook : IP non conforme refusée

    # Échéance (TTL) : commentaire `until=` ignoré par nginx ; un nouveau blocage REMPLACE la ligne
    # (échéance prolongée, jamais de doublon) ; même échéance rejouée = idempotent.
    timed = {**extravars, "deny_until": 1800000000}
    third = await runner.run_playbook(PLAYBOOK_WAF_DENY, timed, timeout=120)
    assert third.ok and third.changed is True, third
    assert deny.read_text(encoding="utf-8").splitlines() == ["203.0.113.77 1; # until=1800000000"]
    again = await runner.run_playbook(PLAYBOOK_WAF_DENY, timed, timeout=120)
    assert again.ok and again.changed is False, again
    evil = await runner.run_playbook(PLAYBOOK_WAF_DENY, {**extravars, "deny_until": "1; evil"}, timeout=120)
    assert not evil.ok  # échéance non numérique refusée
