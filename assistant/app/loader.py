"""Chargement des sources en `Document` LangChain (lecture seule du système de fichiers).

Trois familles de sources, toutes en LECTURE :
  * ``doc``            — fichiers .md de docs/ (runbooks, PCA/PRA, architecture, contrats...)
  * ``decision_table`` — remediation/decision_table.yml (une règle = un document)
  * ``incident``       — journal d'incidents exporté en JSON (un incident = un document)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

import yaml
from langchain_core.documents import Document
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter

_HEADERS = [("#", "h1"), ("##", "h2"), ("###", "h3")]


# --------------------------------------------------------------------------- docs/*.md
def load_markdown_docs(docs_dir: Path) -> list[Document]:
    docs: list[Document] = []
    if not docs_dir.is_dir():
        return docs
    for path in sorted(docs_dir.rglob("*.md")):
        text = path.read_text(encoding="utf-8", errors="replace")
        if text.strip():
            docs.append(Document(page_content=text, metadata={"doc": path.relative_to(docs_dir).as_posix(), "kind": "doc"}))
    return docs


# --------------------------------------------------------------------------- decision table
def load_decision_table(path: Path) -> list[Document]:
    if not path.is_file():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    name = "decision_table.yml"
    docs: list[Document] = []
    defaults = data.get("defaults") or {}
    if defaults:
        lines = ", ".join(f"{k}={v}" for k, v in defaults.items())
        docs.append(
            Document(
                page_content=f"# Table de décision (version {data.get('version', '?')}) - paramètres par défaut\n{lines}",
                metadata={"doc": name, "kind": "decision_table", "section": "defaults"},
            )
        )
    for rule in data.get("rules") or []:
        itype = rule.get("incident_type", "?")
        steps = []
        for i, act in enumerate(rule.get("actions") or [], 1):
            params = act.get("params") or {}
            ptxt = f" ({', '.join(f'{k}={v}' for k, v in params.items())})" if params else ""
            steps.append(f"{i}. {act.get('type')}{ptxt}")
        body = (
            f"# Procédure de remédiation automatique pour l'incident {itype}\n"
            f"Type d'incident : {itype}\n"
            f"Actions exécutées dans l'ordre par le moteur de remédiation :\n" + "\n".join(steps) + "\n"
            f"Vérification après action : {rule.get('verify', 'n/a')}\n"
            f"Escalade si échec : {rule.get('escalation', 'n/a')}"
        )
        docs.append(Document(page_content=body, metadata={"doc": name, "kind": "decision_table", "section": str(itype)}))
    return docs


# --------------------------------------------------------------------------- incident journal
_INCIDENT_KEYS_ORDER = (
    "incident_id", "incident_type", "service", "ts", "detected_at", "anomaly_score",
    "actions", "verified", "result", "status", "mttd_seconds", "mttr_seconds", "summary", "message",
)


def _read_incidents(path: Path) -> list[dict[str, Any]]:
    raw = path.read_text(encoding="utf-8").strip()
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:  # JSONL
        data = [json.loads(line) for line in raw.splitlines() if line.strip()]
    if isinstance(data, dict):
        data = data.get("incidents", [data])
    return [d for d in data if isinstance(d, dict)]


def _fmt(value: Any) -> str:
    if isinstance(value, list):
        return "; ".join(_fmt(v) for v in value)
    if isinstance(value, dict):
        return ", ".join(f"{k}={_fmt(v)}" for k, v in value.items())
    return str(value)


def load_incident_journal(path: Path) -> list[Document]:
    """Un incident -> un document. Tolérant sur le schéma exact de l'export."""
    if not path.is_file():
        return []
    docs: list[Document] = []
    for n, inc in enumerate(_read_incidents(path), 1):
        ident = str(inc.get("incident_id") or inc.get("id") or f"incident-{n}")
        keys = [k for k in _INCIDENT_KEYS_ORDER if k in inc] + [k for k in inc if k not in _INCIDENT_KEYS_ORDER]
        lines = [f"# Journal d'incident {ident} (type {inc.get('incident_type', 'inconnu')})"]
        lines += [f"{k} : {_fmt(inc[k])}" for k in keys]
        docs.append(
            Document(
                page_content="\n".join(lines),
                metadata={"doc": f"journal/{ident}", "kind": "incident", "section": str(inc.get("incident_type", ""))},
            )
        )
    return docs


# --------------------------------------------------------------------------- chunking
def split_documents(docs: Iterable[Document], chunk_size: int = 900, chunk_overlap: int = 120) -> list[Document]:
    """Découpe par titres Markdown puis par taille ; préfixe chaque chunk de son contexte.

    Le préfixe ``[doc > section]`` est inclus dans le texte embarqué : il aide la recherche
    (le nom du runbook / de la section compte) et fournit la provenance au LLM.
    """
    header_splitter = MarkdownHeaderTextSplitter(_HEADERS, strip_headers=False)
    size_splitter = RecursiveCharacterTextSplitter(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    chunks: list[Document] = []
    for doc in docs:
        sections = header_splitter.split_text(doc.page_content) or [Document(page_content=doc.page_content)]
        for sec in sections:
            heading = " > ".join(sec.metadata[h] for _, h in _HEADERS if h in sec.metadata)
            section = heading or doc.metadata.get("section", "")
            for piece in size_splitter.split_text(sec.page_content):
                if not piece.strip():
                    continue
                label = doc.metadata["doc"] + (f" > {section}" if section else "")
                chunks.append(
                    Document(
                        page_content=f"[{label}]\n{piece}",
                        metadata={**doc.metadata, "section": section},
                    )
                )
    return chunks
