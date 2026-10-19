"""Accès Chroma (persistant) via langchain-chroma."""

from __future__ import annotations

from pathlib import Path

from chromadb.config import Settings as ChromaSettings
from langchain_chroma import Chroma

from app.config import Settings
from app.embeddings import backend_id, get_embeddings

_COLLECTION_META = {"hnsw:space": "cosine"}


def open_store(settings: Settings, *, reset: bool = False) -> Chroma:
    """Ouvre (ou recrée si ``reset``) la collection Chroma persistante."""
    settings.chroma_dir.mkdir(parents=True, exist_ok=True)
    client_settings = ChromaSettings(anonymized_telemetry=False, is_persistent=True, persist_directory=str(settings.chroma_dir))
    store = Chroma(
        collection_name=settings.chroma_collection,
        embedding_function=get_embeddings(settings),
        persist_directory=str(settings.chroma_dir),
        client_settings=client_settings,
        collection_metadata={**_COLLECTION_META, "embeddings": backend_id(settings)},
    )
    if reset:
        store.delete_collection()
        store = Chroma(
            collection_name=settings.chroma_collection,
            embedding_function=get_embeddings(settings),
            persist_directory=str(settings.chroma_dir),
            client_settings=client_settings,
            collection_metadata={**_COLLECTION_META, "embeddings": backend_id(settings)},
        )
    return store


def stored_backend(store: Chroma) -> str | None:
    return (store._collection.metadata or {}).get("embeddings")


def count(store: Chroma) -> int:
    return store._collection.count()


def sources_available(settings: Settings) -> bool:
    return (
        Path(settings.docs_dir).is_dir()
        or Path(settings.decision_table_path).is_file()
        or Path(settings.incidents_path).is_file()
    )
