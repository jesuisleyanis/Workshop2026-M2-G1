"""Indexation : sources (docs/*.md, table de décision, journal d'incidents) -> chunks -> Chroma.

Usage :  python -m app.indexer [--docs-dir D] [--decision-table F] [--incidents F] [--chroma-path P]
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

from app.config import SERVICE_NAME, Settings
from app.embeddings import backend_id
from app.loader import load_decision_table, load_incident_journal, load_markdown_docs, split_documents
from app.store import open_store

from resilience_common import get_logger

log = get_logger(SERVICE_NAME)


def build_index(settings: Settings) -> dict[str, int]:
    """Reconstruit l'index depuis les sources. Idempotent (rebuild complet, ids stables)."""
    docs = (
        load_markdown_docs(Path(settings.docs_dir))
        + load_decision_table(Path(settings.decision_table_path))
        + load_incident_journal(Path(settings.incidents_path))
    )
    chunks = split_documents(docs, settings.chunk_size, settings.chunk_overlap)
    store = open_store(settings, reset=True)
    if chunks:
        ids = [hashlib.sha1(f"{c.metadata['doc']}|{i}|{c.page_content}".encode()).hexdigest() for i, c in enumerate(chunks)]
        store.add_documents(chunks, ids=ids)
    stats = {"documents": len(docs), "chunks": len(chunks)}
    log.info(
        f"Index construit : {stats['documents']} documents, {stats['chunks']} chunks "
        f"(embeddings={backend_id(settings)}, chroma={settings.chroma_path})",
        extra={"event": "assistant_index_built"},
    )
    return stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Indexe docs/, la table de décision et le journal d'incidents dans Chroma.")
    parser.add_argument("--docs-dir")
    parser.add_argument("--decision-table")
    parser.add_argument("--incidents")
    parser.add_argument("--chroma-path")
    args = parser.parse_args(argv)
    base = Settings()
    overrides = {
        k: v
        for k, v in {
            "docs_dir": args.docs_dir,
            "decision_table_path": args.decision_table,
            "incidents_path": args.incidents,
            "chroma_path": args.chroma_path,
        }.items()
        if v
    }
    settings = Settings(**{**base.__dict__, **overrides})
    stats = build_index(settings)
    if stats["chunks"] == 0:
        log.error("Aucune source trouvée : index vide", extra={"event": "assistant_index_empty"})
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
