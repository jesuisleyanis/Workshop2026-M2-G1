"""Embeddings.

Deux backends, même interface LangChain `Embeddings` :

* ``hash`` (défaut) — hashing trick lexical : tokens normalisés (minuscules, sans accents,
  snake_case éclaté, pluriels réduits) + bigrammes, projetés dans un espace fixe puis
  normalisés L2. Zéro dépendance lourde (pas de torch), déterministe, instantané, fonctionne
  hors-ligne et **même si Ollama est absent** (mode dégradé : on garde la recherche).
  Limite assumée : similarité *lexicale*, pas sémantique. Largement suffisant pour un corpus
  de runbooks/PCA/PRA où les termes techniques (``service_flood``, ``restore_pg_dump``) sont
  discriminants.
* ``ollama`` — ``OllamaEmbeddings`` (ex. ``nomic-embed-text``) : meilleur rappel sémantique,
  mais requiert Ollama joignable à l'indexation ET à chaque question.

Changer de backend impose de ré-indexer (le nom du backend est stocké dans la collection).
"""

from __future__ import annotations

import hashlib
import math
import re
import unicodedata
from collections import Counter

from langchain_core.embeddings import Embeddings

from app.config import Settings

HASH_DIM = 1024

_STOPWORDS = frozenset(
    """le la les un une des du de d l au aux et ou en a est sont ce cet cette ces se sa son ses
    que qui quoi dont pour par sur sous dans avec sans il elle ils elles on nous vous je tu
    ne pas plus y the of to and is in on for quel quelle quels quelles comment quand faut
    faire fait ete etre avoir c n s t qu""".split()
)
_TOKEN_RE = re.compile(r"[a-z0-9]+(?:_[a-z0-9]+)*")


def _strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def _stem(token: str) -> str:
    """Réduction minimale des pluriels (français/anglais), volontairement simple."""
    if len(token) > 4 and token.endswith(("s", "x")):
        return token[:-1]
    return token


def tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    for raw in _TOKEN_RE.findall(_strip_accents(text.lower())):
        parts = raw.split("_")
        # Le token composé (service_flood) ET ses parties (service, flood) : une question
        # « inondation de service » ou « flood » doit retrouver l'identifiant exact.
        candidates = [raw, *parts] if len(parts) > 1 else [raw]
        for tok in candidates:
            tok = _stem(tok)
            if tok and tok not in _STOPWORDS and len(tok) > 1:
                tokens.append(tok)
    return tokens


def _bucket(feature: str) -> tuple[int, float]:
    digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
    value = int.from_bytes(digest, "big")
    return value % HASH_DIM, 1.0 if (value >> 63) & 1 else -1.0


class HashEmbeddings(Embeddings):
    """Embeddings lexicaux par hashing (déterministes, sans état, sans réseau)."""

    name = "hash-v1"

    def _embed(self, text: str) -> list[float]:
        tokens = tokenize(text)
        features: Counter[str] = Counter(tokens)
        # Bigrammes : poids moindre, ils départagent les passages partageant les mêmes mots.
        for a, b in zip(tokens, tokens[1:], strict=False):
            features[f"{a} {b}"] += 0.5
        vec = [0.0] * HASH_DIM
        for feat, count in features.items():
            idx, sign = _bucket(feat)
            weight = 1.0 + math.log(count) if count >= 1 else count
            vec[idx] += sign * weight
        norm = math.sqrt(sum(v * v for v in vec))
        return [v / norm for v in vec] if norm else vec

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)


def backend_id(settings: Settings) -> str:
    if settings.embeddings_backend == "ollama":
        return f"ollama:{settings.ollama_embed_model}"
    return HashEmbeddings.name


def get_embeddings(settings: Settings) -> Embeddings:
    backend = settings.embeddings_backend.lower()
    if backend == "hash":
        return HashEmbeddings()
    if backend == "ollama":
        from langchain_ollama import OllamaEmbeddings

        return OllamaEmbeddings(model=settings.ollama_embed_model, base_url=settings.ollama_base_url)
    raise ValueError(f"EMBEDDINGS_BACKEND inconnu : {settings.embeddings_backend!r} (hash|ollama)")
