"""Configuration par variables d'environnement (aucun secret requis)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

SERVICE_NAME = "assistant"


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


def _env_bool(name: str, default: bool) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    # --- LLM (Ollama, modèle <= 8B imposé par le sujet §3.3) ---
    ollama_base_url: str = field(default_factory=lambda: _env("OLLAMA_BASE_URL", "http://ollama:11434"))
    ollama_model: str = field(default_factory=lambda: _env("OLLAMA_MODEL", "qwen2.5:7b"))
    ollama_timeout_s: float = field(default_factory=lambda: float(_env("OLLAMA_TIMEOUT_S", "120")))
    ollama_probe_timeout_s: float = field(default_factory=lambda: float(_env("OLLAMA_PROBE_TIMEOUT_S", "2")))
    # --- Embeddings : "hash" (local, sans dépendance, défaut) | "ollama" ---
    embeddings_backend: str = field(default_factory=lambda: _env("EMBEDDINGS_BACKEND", "hash"))
    ollama_embed_model: str = field(default_factory=lambda: _env("OLLAMA_EMBED_MODEL", "nomic-embed-text"))
    # --- Chroma ---
    chroma_path: str = field(default_factory=lambda: _env("CHROMA_PATH", "/data/chroma"))
    chroma_collection: str = field(default_factory=lambda: _env("CHROMA_COLLECTION", "resilience_knowledge"))
    # --- Sources d'indexation (montées en lecture seule) ---
    docs_dir: str = field(default_factory=lambda: _env("DOCS_DIR", "/data/docs"))
    decision_table_path: str = field(default_factory=lambda: _env("DECISION_TABLE_PATH", "/data/remediation/decision_table.yml"))
    incidents_path: str = field(default_factory=lambda: _env("INCIDENTS_PATH", "/data/incidents/incidents.json"))
    # --- RAG ---
    chunk_size: int = field(default_factory=lambda: int(_env("CHUNK_SIZE", "900")))
    chunk_overlap: int = field(default_factory=lambda: int(_env("CHUNK_OVERLAP", "120")))
    top_k: int = field(default_factory=lambda: int(_env("RAG_TOP_K", "4")))
    min_score: float = field(default_factory=lambda: float(_env("RAG_MIN_SCORE", "0.05")))
    max_question_chars: int = field(default_factory=lambda: int(_env("MAX_QUESTION_CHARS", "1000")))
    # Indexe au démarrage si la collection est vide et que des sources existent.
    auto_index: bool = field(default_factory=lambda: _env_bool("AUTO_INDEX", True))
    # Origines autorisées à embarquer l'UI dans une iframe (CSP frame-ancestors), ex. "http://localhost:5173".
    frame_ancestors: str = field(default_factory=lambda: _env("FRAME_ANCESTORS", ""))
    metrics_enabled: bool = field(default_factory=lambda: _env_bool("METRICS_ENABLED", True))

    @property
    def chroma_dir(self) -> Path:
        return Path(self.chroma_path)
