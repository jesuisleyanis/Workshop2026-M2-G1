"""Contrat de la Console Red Team : garde-fous côté serveur non contournables.

Tourne en dry-run (RESILIENCE_CONSOLE_DRY=1) : aucune attaque réelle n'est lancée,
on vérifie le clamp des plafonds, la liste blanche, la validation de cible et l'argv.
Sauté si fastapi n'est pas installé (voir attacks/console/requirements.txt).
"""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

CONSOLE = Path(__file__).resolve().parents[1] / "console"


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("RESILIENCE_CONSOLE_DRY", "1")
    sys.path.insert(0, str(CONSOLE))
    import server  # type: ignore
    server = importlib.reload(server)
    try:
        yield TestClient(server.app), server
    finally:
        sys.path.remove(str(CONSOLE))


def test_scenarios_exposes_caps_and_launchable(client):
    c, _ = client
    d = c.get("/api/scenarios").json()
    assert d["max_duration"] == 60 and d["max_rate"] == 100
    names = {s["name"]: s for s in d["scenarios"]}
    # data_corruption présent mais NON lançable depuis la console (opérateur-only).
    assert names["data_corruption"]["launchable"] is False
    assert names["service_flood"]["launchable"] is True


def test_run_clamps_duration_and_rate(client):
    c, server = client
    r = c.post("/api/run", json={"scenario": "service_flood", "duration": 999, "rate": 9999}).json()
    assert r["duration"] == 60 and r["rate"] == 100           # plafonnés
    assert "--duration" in server.runner.last_argv
    i = server.runner.last_argv.index("--duration")
    assert server.runner.last_argv[i + 1] == "60"


def test_run_rejects_unknown_scenario(client):
    c, _ = client
    assert c.post("/api/run", json={"scenario": "rm_rf"}).status_code == 422


def test_run_rejects_non_launchable_scenario(client):
    c, _ = client
    assert c.post("/api/run", json={"scenario": "data_corruption"}).status_code == 422


def test_invalid_target_is_rejected(client):
    c, _ = client
    assert c.post("/api/run", json={"scenario": "service_flood",
                                    "target": "file:///etc/passwd"}).status_code == 422


def test_no_concurrent_runs(client):
    c, server = client
    # en dry-run le process n'est pas réellement lancé ; on force l'état "running".
    class _P:
        def poll(self):
            return None
    c.post("/api/run", json={"scenario": "service_flood"})
    server.runner.proc = _P()
    assert c.post("/api/run", json={"scenario": "auth_abuse"}).status_code == 409


def test_server_binds_localhost_only():
    # Garde-fou : jamais 0.0.0.0 (le service déclenche des attaques).
    text = (CONSOLE / "server.py").read_text(encoding="utf-8")
    assert 'host="127.0.0.1"' in text
    assert 'host="0.0.0.0"' not in text and 'host=0.0.0.0' not in text
