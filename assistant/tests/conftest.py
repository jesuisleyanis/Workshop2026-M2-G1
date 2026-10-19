"""Fixtures communes. Aucun test n'a de dépendance réseau : Ollama est mocké / sondé en faux."""

from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage

os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")

from app.config import Settings  # noqa: E402
from app.indexer import build_index  # noqa: E402
from app.store import open_store  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"


def make_settings(chroma_path: Path, **overrides) -> Settings:
    base = Settings()
    return replace(
        base,
        docs_dir=str(FIXTURES / "docs"),
        decision_table_path=str(FIXTURES / "decision_table.yml"),
        incidents_path=str(FIXTURES / "incidents.json"),
        chroma_path=str(chroma_path),
        embeddings_backend="hash",
        metrics_enabled=False,
        auto_index=False,
        **overrides,
    )


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """Par défaut Ollama est 'injoignable' pour la sonde /ready (aucun appel réseau)."""
    monkeypatch.setattr("app.main.ollama_reachable", lambda _s: False)


@pytest.fixture
def settings(tmp_path) -> Settings:
    return make_settings(tmp_path / "chroma")


@pytest.fixture
def indexed(settings):
    """(settings, store) avec le petit corpus de fixtures déjà indexé."""
    build_index(settings)
    return settings, open_store(settings)


@pytest.fixture
def fake_llm():
    llm = MagicMock(name="ChatOllama")
    llm.invoke.return_value = AIMessage(content="Réponse simulée [1].")
    return llm
