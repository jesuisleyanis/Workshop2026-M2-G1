"""Journal d'incidents (SQLite local) : incidents, actions, vérifications, timeline.

SQLite suffit (un seul processus écrivain, volumes faibles) et ne crée aucune dépendance
réseau supplémentaire pour le moteur. Le fichier vit sur un volume dédié en écriture ;
le reste du conteneur est en lecture seule.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime
from typing import Any

from models import iso, parse_iso

SCHEMA = """
CREATE TABLE IF NOT EXISTS incidents (
  incident_id TEXT PRIMARY KEY,
  incident_key TEXT NOT NULL,
  incident_type TEXT NOT NULL,
  service TEXT NOT NULL,
  event_id TEXT NOT NULL,
  event_json TEXT NOT NULL,
  status TEXT NOT NULL,
  dry_run INTEGER NOT NULL DEFAULT 0,
  attempts INTEGER NOT NULL DEFAULT 0,
  detected_at TEXT NOT NULL,
  first_action_at TEXT,
  last_action_at TEXT,
  closed_at TEXT,
  mttd_seconds REAL,
  mttr_seconds REAL,
  reason TEXT
);
CREATE INDEX IF NOT EXISTS ix_inc_key ON incidents(incident_key);
CREATE UNIQUE INDEX IF NOT EXISTS ux_inc_event ON incidents(event_id);
CREATE TABLE IF NOT EXISTS actions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  incident_id TEXT NOT NULL,
  attempt INTEGER NOT NULL,
  ts TEXT NOT NULL,
  action_type TEXT NOT NULL,
  params_json TEXT NOT NULL,
  result TEXT NOT NULL,
  detail TEXT,
  duration_ms INTEGER
);
CREATE TABLE IF NOT EXISTS verifications (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  incident_id TEXT NOT NULL,
  attempt INTEGER NOT NULL,
  ts TEXT NOT NULL,
  ok INTEGER NOT NULL,
  rc INTEGER,
  detail TEXT
);
CREATE TABLE IF NOT EXISTS timeline (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  incident_id TEXT NOT NULL,
  incident_type TEXT NOT NULL,
  ts TEXT NOT NULL,
  phase TEXT NOT NULL,
  status TEXT NOT NULL,
  message TEXT NOT NULL,
  data_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_tl_inc ON timeline(incident_id);
"""

FINAL_STATUSES = ("closed", "escalated", "dry_run", "interrupted")


class Journal:
    def __init__(self, path: str = ":memory:") -> None:
        self._lock = threading.RLock()
        # uri : permet `file:...?mode=ro` (export_journal.py) ; les chemins simples sont inchangés.
        self._db = sqlite3.connect(path, check_same_thread=False, uri=path.startswith("file:"))
        self._db.row_factory = sqlite3.Row
        with self._lock:
            self._db.executescript(SCHEMA)
            self._db.commit()

    # --- utilitaires -------------------------------------------------------------
    def _exec(self, sql: str, args: tuple = ()) -> sqlite3.Cursor:
        with self._lock:
            cur = self._db.execute(sql, args)
            self._db.commit()
            return cur

    def _query(self, sql: str, args: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._db.execute(sql, args).fetchall()

    def ping(self) -> bool:
        try:
            self._query("SELECT 1")
            return True
        except sqlite3.Error:
            return False

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def recover_orphans(self) -> int:
        """Au redémarrage, un incident encore `in_progress` a été interrompu."""
        cur = self._exec(
            "UPDATE incidents SET status='interrupted', reason='moteur redémarré en cours d''incident' "
            "WHERE status='in_progress'"
        )
        return cur.rowcount

    # --- incidents ---------------------------------------------------------------
    def create_incident(self, *, incident_id: str, key: str, incident_type: str, service: str,
                        event_id: str, event_json: str, detected_at: datetime, dry_run: bool) -> None:
        self._exec(
            "INSERT INTO incidents(incident_id, incident_key, incident_type, service, event_id, event_json,"
            " status, dry_run, detected_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (incident_id, key, incident_type, service, event_id, event_json, "in_progress",
             int(dry_run), iso(detected_at)),
        )

    def set_attempts(self, incident_id: str, attempts: int) -> None:
        self._exec("UPDATE incidents SET attempts=? WHERE incident_id=?", (attempts, incident_id))

    def mark_action(self, incident_id: str, ts: datetime, first: bool, mttd: float | None) -> None:
        if first:
            self._exec("UPDATE incidents SET first_action_at=?, last_action_at=?, mttd_seconds=? "
                       "WHERE incident_id=?", (iso(ts), iso(ts), mttd, incident_id))
        else:
            self._exec("UPDATE incidents SET last_action_at=? WHERE incident_id=?", (iso(ts), incident_id))

    def finish(self, incident_id: str, status: str, closed_at: datetime, *,
               mttr: float | None = None, reason: str | None = None) -> None:
        self._exec("UPDATE incidents SET status=?, closed_at=?, mttr_seconds=?, reason=? WHERE incident_id=?",
                   (status, iso(closed_at), mttr, reason, incident_id))

    def incident_for_event(self, event_id: str) -> str | None:
        rows = self._query("SELECT incident_id FROM incidents WHERE event_id=?", (event_id,))
        return rows[0]["incident_id"] if rows else None

    def last_action_at(self, key: str) -> datetime | None:
        rows = self._query("SELECT MAX(last_action_at) AS t FROM incidents WHERE incident_key=?", (key,))
        return parse_iso(rows[0]["t"]) if rows and rows[0]["t"] else None

    def last_incident_id(self, key: str) -> str | None:
        rows = self._query("SELECT incident_id FROM incidents WHERE incident_key=? "
                           "ORDER BY detected_at DESC, rowid DESC LIMIT 1", (key,))
        return rows[0]["incident_id"] if rows else None

    def get_incident(self, incident_id: str) -> dict[str, Any] | None:
        rows = self._query("SELECT * FROM incidents WHERE incident_id=?", (incident_id,))
        if not rows:
            return None
        inc = self._incident_dict(rows[0])
        inc["actions"] = [
            {"ts": r["ts"], "attempt": r["attempt"], "type": r["action_type"],
             "params": json.loads(r["params_json"]), "result": r["result"],
             "detail": r["detail"], "duration_ms": r["duration_ms"]}
            for r in self._query("SELECT * FROM actions WHERE incident_id=? ORDER BY id", (incident_id,))
        ]
        inc["verifications"] = [
            {"ts": r["ts"], "attempt": r["attempt"], "ok": bool(r["ok"]), "rc": r["rc"], "detail": r["detail"]}
            for r in self._query("SELECT * FROM verifications WHERE incident_id=? ORDER BY id", (incident_id,))
        ]
        inc["timeline"] = self.timeline_since(0, incident_id, limit=1000)
        return inc

    def last_blocks(self) -> list[dict[str, Any]]:
        """Blocages WAF réussis (le plus récent d'abord) avec l'incident qui les a déclenchés."""
        rows = self._query(
            "SELECT a.ts, a.action_type, a.detail, a.incident_id, i.incident_type FROM actions a "
            "JOIN incidents i ON i.incident_id = a.incident_id "
            "WHERE a.action_type IN ('waf_block_ip', 'waf_blacklist_ip') AND a.result = 'success' "
            "ORDER BY a.id DESC")
        return [dict(r) for r in rows]

    def list_incidents(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = self._query("SELECT * FROM incidents ORDER BY detected_at DESC, rowid DESC LIMIT ?", (limit,))
        return [self._incident_dict(r) for r in rows]

    @staticmethod
    def _incident_dict(r: sqlite3.Row) -> dict[str, Any]:
        return {
            "incident_id": r["incident_id"], "incident_type": r["incident_type"], "service": r["service"],
            "event_id": r["event_id"], "status": r["status"], "dry_run": bool(r["dry_run"]),
            "attempts": r["attempts"], "detected_at": r["detected_at"], "first_action_at": r["first_action_at"],
            "closed_at": r["closed_at"], "mttd_seconds": r["mttd_seconds"], "mttr_seconds": r["mttr_seconds"],
            "reason": r["reason"],
        }

    # --- actions / vérifications ---------------------------------------------------
    def add_action(self, incident_id: str, attempt: int, ts: datetime, action_type: str,
                   params: dict[str, Any], result: str, detail: str, duration_ms: int) -> None:
        self._exec("INSERT INTO actions(incident_id, attempt, ts, action_type, params_json, result, detail,"
                   " duration_ms) VALUES (?,?,?,?,?,?,?,?)",
                   (incident_id, attempt, iso(ts), action_type, json.dumps(params), result, detail, duration_ms))

    def add_verification(self, incident_id: str, attempt: int, ts: datetime, ok: bool,
                         rc: int | None, detail: str) -> None:
        self._exec("INSERT INTO verifications(incident_id, attempt, ts, ok, rc, detail) VALUES (?,?,?,?,?,?)",
                   (incident_id, attempt, iso(ts), int(ok), rc, detail))

    # --- timeline ------------------------------------------------------------------
    def add_timeline(self, *, incident_id: str, incident_type: str, ts: datetime, phase: str,
                     status: str, message: str, data: dict[str, Any]) -> dict[str, Any]:
        cur = self._exec("INSERT INTO timeline(incident_id, incident_type, ts, phase, status, message,"
                         " data_json) VALUES (?,?,?,?,?,?,?)",
                         (incident_id, incident_type, iso(ts), phase, status, message, json.dumps(data)))
        return {"id": cur.lastrowid, "incident_id": incident_id, "incident_type": incident_type,
                "ts": iso(ts), "phase": phase, "status": status, "message": message, "data": data}

    def timeline_since(self, since: int, incident_id: str | None = None, limit: int = 500) -> list[dict[str, Any]]:
        sql, args = "SELECT * FROM timeline WHERE id > ?", [since]
        if incident_id:
            sql += " AND incident_id = ?"
            args.append(incident_id)
        sql += " ORDER BY id LIMIT ?"
        args.append(limit)
        return [{"id": r["id"], "incident_id": r["incident_id"], "incident_type": r["incident_type"],
                 "ts": r["ts"], "phase": r["phase"], "status": r["status"], "message": r["message"],
                 "data": json.loads(r["data_json"])} for r in self._query(sql, tuple(args))]

    def latest_timeline_id(self) -> int:
        rows = self._query("SELECT COALESCE(MAX(id), 0) AS m FROM timeline")
        return int(rows[0]["m"])
