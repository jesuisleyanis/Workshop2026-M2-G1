"""Export JSON du journal d'incidents pour l'assistant RAG (commande d'exploitation).

L'assistant n'indexe qu'une COPIE (assistant/CAHIER-DES-CHARGES.md §2.4) : il ne lit jamais
l'API du moteur ni sa base SQLite. Cette CLI ouvre la base en lecture seule et écrit le
fichier de façon atomique (temporaire + os.replace) : l'assistant ne lit jamais un export partiel.

    python export_journal.py [--db PATH] [--out PATH] [--limit N]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

from config import Settings
from journal import Journal
from models import iso, utcnow

DEFAULT_OUT = "/var/lib/remediation/export/incidents.json"


def export(db: str, out: str, limit: int = 200) -> int:
    """Écrit {"exported_at", "incidents": [...]} dans `out` ; renvoie le nombre d'incidents."""
    # mode=ro : aucune écriture possible, et pas de base vide créée si le chemin est faux.
    journal = Journal(Path(db).resolve().as_uri() + "?mode=ro")
    try:
        incidents = [journal.get_incident(i["incident_id"]) for i in journal.list_incidents(limit)]
    finally:
        journal.close()
    payload = {"exported_at": iso(utcnow()), "incidents": incidents}
    target = Path(out)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=".incidents-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.chmod(tmp, 0o644)  # mkstemp crée en 0600 : l'assistant (autre uid) doit pouvoir lire
        os.replace(tmp, target)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return len(incidents)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Exporte le journal d'incidents en JSON (lecture seule).")
    parser.add_argument("--db", default=Settings.from_env().db_path, help="base SQLite (défaut : INCIDENTS_DB)")
    parser.add_argument("--out", default=os.environ.get("INCIDENTS_EXPORT_PATH", DEFAULT_OUT),
                        help="fichier JSON produit (défaut : INCIDENTS_EXPORT_PATH)")
    parser.add_argument("--limit", type=int, default=200, help="nombre max d'incidents, les plus récents (200)")
    args = parser.parse_args(argv)
    if not Path(args.db).is_file():
        print(f"erreur : base d'incidents introuvable : {args.db}", file=sys.stderr)
        return 2
    n = export(args.db, args.out, args.limit)
    print(f"{n} incident(s) exporté(s) vers {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
