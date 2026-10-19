"""Export JSON du journal pour l'assistant : contenu complet, limite, écriture atomique, lecture seule."""

from __future__ import annotations

import json
import sqlite3
from datetime import timedelta
from pathlib import Path

import pytest

from conftest import T0
from export_journal import main
from journal import Journal


@pytest.fixture
def db(tmp_path):
    path = str(tmp_path / "incidents.db")
    j = Journal(path)
    for n, (itype, svc) in enumerate([("service_flood", "payment-api"), ("auth_abuse", "auth")], 1):
        iid, ts = f"inc-{n}", T0 + timedelta(minutes=n)
        j.create_incident(incident_id=iid, key=f"{itype}:{svc}", incident_type=itype, service=svc,
                          event_id=f"evt-{n}", event_json="{}", detected_at=ts, dry_run=False)
        j.add_action(iid, 1, ts, "restart_service", {"service": svc}, "ok", "redémarré", 120)
        j.add_verification(iid, 1, ts, True, 0, "verify_tx ok")
        j.add_timeline(incident_id=iid, incident_type=itype, ts=ts, phase="action", status="ok",
                       message="restart_service ok", data={"service": svc})
        j.finish(iid, "closed", ts + timedelta(seconds=41), mttr=41.0)
    j.close()
    return path


def test_export_writes_full_incidents(db, tmp_path, capsys):
    out = tmp_path / "export" / "incidents.json"  # dossier parent créé à la volée
    assert main(["--db", db, "--out", str(out)]) == 0
    assert "2 incident(s)" in capsys.readouterr().out

    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["exported_at"].endswith("Z")
    first = data["incidents"][0]  # le plus récent d'abord (ordre de list_incidents)
    assert first["incident_id"] == "inc-2" and first["status"] == "closed" and first["mttr_seconds"] == 41.0
    assert first["actions"] == [{"ts": first["actions"][0]["ts"], "attempt": 1, "type": "restart_service",
                                 "params": {"service": "auth"}, "result": "ok", "detail": "redémarré",
                                 "duration_ms": 120}]
    assert first["verifications"][0]["ok"] is True
    assert first["timeline"][0]["message"] == "restart_service ok"
    assert "redémarré" in out.read_text(encoding="utf-8")  # UTF-8 brut, pas d'échappement \u
    assert [p.name for p in out.parent.iterdir()] == ["incidents.json"]  # aucun temporaire résiduel


def test_export_limit(db, tmp_path):
    out = tmp_path / "incidents.json"
    assert main(["--db", db, "--out", str(out), "--limit", "1"]) == 0
    assert [i["incident_id"] for i in json.loads(out.read_text(encoding="utf-8"))["incidents"]] == ["inc-2"]


def test_export_is_read_only_and_replaces_previous(db, tmp_path):
    out = tmp_path / "incidents.json"
    out.write_text("ancien", encoding="utf-8")
    before = Path(db).read_bytes()
    assert main(["--db", db, "--out", str(out)]) == 0
    assert len(json.loads(out.read_text(encoding="utf-8"))["incidents"]) == 2
    assert Path(db).read_bytes() == before  # base intacte


def test_read_only_connection_refuses_writes(db):
    j = Journal(Path(db).resolve().as_uri() + "?mode=ro")
    with pytest.raises(sqlite3.OperationalError, match="readonly"):
        j.finish("inc-1", "escalated", T0)
    j.close()


def test_missing_db_fails_without_creating_it(tmp_path, capsys):
    missing, out = tmp_path / "absent.db", tmp_path / "incidents.json"
    assert main(["--db", str(missing), "--out", str(out)]) == 2
    assert "introuvable" in capsys.readouterr().err
    assert not missing.exists() and not out.exists()
