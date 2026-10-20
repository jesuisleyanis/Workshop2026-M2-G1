"""Abstraction de reconnaissance faciale + backend stub déterministe.

Le service dépend de l'interface `Recognizer`, jamais d'un modèle concret. Deux backends :

- `stub` (défaut) : embedding déterministe dérivé des octets de l'image (sha256). Permet des
  tests reproductibles du *plumbing* du service **sans modèle ni matériel** (image identique =>
  correspondance, image différente => non-correspondance). La qualité de reconnaissance réelle
  est validée en recette avec le backend `insightface`.
- `insightface` : InsightFace `buffalo_s` (ONNX Runtime CPU), embeddings 512-d, similarité cosinus.
  Chargé paresseusement, uniquement en recette (dépendances non installées pour les tests).

Un embedding est (dé)sérialisé via le module `array` (float32) — aucune dépendance numpy côté noyau.
"""

from __future__ import annotations

import hashlib
import math
from array import array
from typing import Protocol, runtime_checkable


class NoFaceError(ValueError):
    """Aucun visage exploitable dans l'image fournie."""


def serialize_embedding(vector: list[float]) -> bytes:
    """Vecteur -> octets float32 (stockés en base, jamais l'image)."""
    return array("f", vector).tobytes()


def deserialize_embedding(blob: bytes) -> list[float]:
    arr = array("f")
    arr.frombytes(blob)
    return list(arr)


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if len(a) != len(b):
        raise ValueError("dimensions d'embedding incompatibles")
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


@runtime_checkable
class Recognizer(Protocol):
    model_version: str
    threshold: float

    def embed(self, image: bytes) -> list[float]:
        """Octets d'image -> embedding. Lève NoFaceError si aucun visage exploitable."""
        ...


class StubRecognizer:
    """Embedding déterministe pour tests reproductibles (pas un vrai modèle)."""

    model_version = "stub-1.0"
    _DIM = 64

    def __init__(self, threshold: float = 0.6) -> None:
        self.threshold = threshold

    def embed(self, image: bytes) -> list[float]:
        if not image:
            raise NoFaceError("image vide")
        # Déroule sha256 en un vecteur déterministe : image identique => embedding identique.
        # Composantes centrées sur 0 ([-1, 1]) : deux images différentes donnent des vecteurs
        # quasi orthogonaux (cosinus ~ 0), une image identique un cosinus de 1.0.
        vec: list[float] = []
        seed = image
        while len(vec) < self._DIM:
            seed = hashlib.sha256(seed).digest()
            vec.extend((b / 127.5) - 1.0 for b in seed)
        return vec[: self._DIM]


def build_recognizer(backend: str, threshold: float | None = None) -> Recognizer:
    """Fabrique le backend demandé. `insightface` est importé paresseusement (recette)."""
    if backend == "stub":
        return StubRecognizer(threshold if threshold is not None else 0.6)
    if backend == "insightface":  # pragma: no cover - validé en recette, deps non installées
        from face_id.backends.insightface_backend import InsightFaceRecognizer

        return InsightFaceRecognizer(threshold if threshold is not None else 0.35)
    raise ValueError(f"backend de reconnaissance inconnu: {backend!r}")
