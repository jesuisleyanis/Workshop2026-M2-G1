from dataclasses import replace
from pathlib import Path

from app.indexer import build_index, main
from app.loader import load_decision_table, load_incident_journal, load_markdown_docs, split_documents
from app.store import count, open_store, stored_backend

from tests.conftest import FIXTURES, make_settings


def test_chunks_are_produced_with_provenance():
    docs = load_markdown_docs(FIXTURES / "docs")
    chunks = split_documents(docs)
    assert len(docs) == 3
    assert len(chunks) >= 3
    flood = [c for c in chunks if c.metadata["doc"] == "runbook-service-flood.md"]
    assert flood and all(c.metadata["kind"] == "doc" for c in flood)
    # le préfixe de provenance [doc > section] est dans le texte embarqué
    assert any(c.page_content.startswith("[runbook-service-flood.md > ") for c in flood)


def test_long_documents_are_split_by_size():
    from langchain_core.documents import Document

    long_doc = Document(page_content="# Titre\n" + ("phrase de remplissage. " * 200), metadata={"doc": "x.md", "kind": "doc"})
    chunks = split_documents([long_doc], chunk_size=300, chunk_overlap=30)
    assert len(chunks) > 5
    assert all(len(c.page_content) <= 300 + len("[x.md > Titre]\n") for c in chunks)


def test_decision_table_one_document_per_rule():
    docs = load_decision_table(FIXTURES / "decision_table.yml")
    kinds = {d.metadata["section"] for d in docs}
    assert kinds == {"defaults", "auth_abuse", "unknown"}
    auth = next(d for d in docs if d.metadata["section"] == "auth_abuse")
    assert "waf_block_ip" in auth.page_content and "tighten_rate_limit" in auth.page_content


def test_incident_journal_json_and_jsonl(tmp_path):
    docs = load_incident_journal(FIXTURES / "incidents.json")
    assert [d.metadata["doc"] for d in docs] == ["journal/inc-0001", "journal/inc-0002"]
    assert "mttr_seconds : 41" in docs[0].page_content

    jsonl = tmp_path / "j.jsonl"
    jsonl.write_text('{"incident_id": "a"}\n{"incident_id": "b"}\n', encoding="utf-8")
    assert len(load_incident_journal(jsonl)) == 2
    assert load_incident_journal(tmp_path / "absent.json") == []  # journal optionnel


def test_build_index_populates_persistent_chroma(settings):
    stats = build_index(settings)
    assert stats["documents"] == 3 + 3 + 2  # md + (defaults + 2 règles) + 2 incidents
    assert stats["chunks"] >= stats["documents"]

    # Persistance : un nouveau client sur le même chemin relit les mêmes données.
    reopened = open_store(settings)
    assert count(reopened) == stats["chunks"]
    assert stored_backend(reopened) == "hash-v1"
    kinds = {m["kind"] for m in reopened.get()["metadatas"]}
    assert kinds == {"doc", "decision_table", "incident"}


def test_reindex_is_idempotent(settings):
    first = build_index(settings)
    second = build_index(settings)
    assert first == second
    assert count(open_store(settings)) == second["chunks"]


def test_index_without_optional_sources(settings):
    s = replace(settings, decision_table_path="/nonexistent.yml", incidents_path="/nonexistent.json")
    stats = build_index(s)
    assert stats["documents"] == 3


def test_cli_returns_error_when_no_source(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    rc = main(["--docs-dir", str(empty), "--decision-table", str(tmp_path / "n.yml"),
               "--incidents", str(tmp_path / "n.json"), "--chroma-path", str(tmp_path / "c")])
    assert rc == 1


def test_cli_indexes_fixtures(tmp_path):
    rc = main(["--docs-dir", str(FIXTURES / "docs"), "--decision-table", str(FIXTURES / "decision_table.yml"),
               "--incidents", str(FIXTURES / "incidents.json"), "--chroma-path", str(tmp_path / "c")])
    assert rc == 0
    s = make_settings(Path(tmp_path / "c"))
    assert count(open_store(s)) > 0
