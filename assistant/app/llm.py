"""Accès au LLM local (Ollama) via LangChain, et sonde de joignabilité.

Frontière de sécurité : ce module n'expose QUE de la génération de texte. Aucun outil
(tool calling), aucun agent, aucune exécution de commande n'est branché au modèle.
"""

from __future__ import annotations

import httpx
from langchain_core.language_models.chat_models import BaseChatModel

from app.config import Settings


def build_llm(settings: Settings) -> BaseChatModel:
    from langchain_ollama import ChatOllama

    return ChatOllama(
        model=settings.ollama_model,
        base_url=settings.ollama_base_url,
        temperature=0.1,
        client_kwargs={"timeout": settings.ollama_timeout_s},
    )


def ollama_reachable(settings: Settings) -> bool:
    """Sonde non bloquante (timeout court) : Ollama répond-il sur /api/tags ?"""
    try:
        r = httpx.get(f"{settings.ollama_base_url.rstrip('/')}/api/tags", timeout=settings.ollama_probe_timeout_s)
        return r.status_code == 200
    except httpx.HTTPError:
        return False
