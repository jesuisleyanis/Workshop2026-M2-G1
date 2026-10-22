"""Abstraction de reconnaissance faciale (v2) + backend stub déterministe.

Le service dépend de l'interface `Recognizer`, jamais d'un modèle concret. Trois backends :

- `stub` (défaut) : images de test de la forme `b"<pose>|<identite>"` (ex. `b"face|alice"`).
  L'embedding ne dépend que de l'identité, la pose est lue dans l'image. Permet des tests
  reproductibles du *plumbing* du service **sans modèle ni matériel**.
- `team` : `face_recognition` (dlib), gabarits 128-d, distance euclidienne, pose par landmarks.
- `insightface` : InsightFace `buffalo_s` (ONNX Runtime CPU), embeddings 512-d, distance
  `1 - cosinus`. Les deux backends réels sont chargés paresseusement, uniquement en recette.

Contrat v2 : `analyze()` renvoie un `FaceSample` (embedding + pose détectée) ; `distance()` est
une distance (plus petit = plus proche) comparée à `threshold`.

Un embedding est (dé)sérialisé via le module `array` (float32) — aucune dépendance numpy côté noyau.
"""

from __future__ import annotations

import hashlib
import math
from array import array
from dataclasses import dataclass
from typing import Protocol, runtime_checkable


class NoFaceError(ValueError):
    """Aucun visage exploitable dans l'image fournie."""


class MultipleFacesError(ValueError):
    """Plusieurs visages dans l'image : l'échantillon est ambigu, il est refusé."""


@dataclass(frozen=True)
class FaceSample:
    """Résultat d'analyse d'une image : gabarit du visage + pose détectée (None si indéterminée)."""

    embedding: list[float]
    pose: str | None


def serialize_embedding(vector: list[float]) -> bytes:
    """Vecteur -> octets float32."""
    return array("f", vector).tobytes()


def deserialize_embedding(blob: bytes) -> list[float]:
    arr = array("f")
    arr.frombytes(blob)
    return list(arr)


def euclidean(a: list[float], b: list[float]) -> float:
    if len(a) != len(b):
        raise ValueError("dimensions d'embedding incompatibles")
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b, strict=True)))


@runtime_checkable
class Recognizer(Protocol):
    model_version: str
    threshold: float  # distance max (plus petit = plus proche)

    def analyze(self, image: bytes, *, precise: bool = False) -> FaceSample:
        """Octets d'image -> embedding + pose.

        Lève NoFaceError (0 visage) ou MultipleFacesError (>1 visage). `precise=True` demande
        un calcul plus coûteux (ex. plus de jitters) pour l'enrôlement.
        """
        ...

    def distance(self, a: list[float], b: list[float]) -> float:
        """Distance entre deux embeddings (plus petit = plus proche)."""
        ...


class StubRecognizer:
    """Reconnaissance factice déterministe pour tests reproductibles (pas un vrai modèle).

    Image de test = `b"<pose>|<identite>"` ; `b"none"` (ou vide) -> NoFaceError ; `b"many"` ->
    MultipleFacesError ; pose hors face/gauche/droite -> pose None. L'embedding (16 floats dans
    [-1, 1]) ne dépend que de l'identité : même identité => distance 0, identités différentes
    => distance très supérieure au seuil.
    """

    model_version = "stub-2.0"
    _DIM = 16
    _POSES = frozenset({"face", "gauche", "droite"})

    def __init__(self, threshold: float = 0.6) -> None:
        self.threshold = threshold

    def analyze(self, image: bytes, *, precise: bool = False) -> FaceSample:
        if not image or image == b"none":
            raise NoFaceError("aucun visage")
        if image == b"many":
            raise MultipleFacesError("plusieurs visages")
        pose_raw, sep, identity = image.partition(b"|")
        if not sep:  # pas de pose indiquée : toute l'image est l'identité
            pose_raw, identity = b"", image
        digest = hashlib.sha256(identity).digest()
        embedding = [(b / 127.5) - 1.0 for b in digest[: self._DIM]]
        pose = pose_raw.decode(errors="replace")
        return FaceSample(embedding, pose if pose in self._POSES else None)

    def distance(self, a: list[float], b: list[float]) -> float:
        return euclidean(a, b)


def build_recognizer(backend: str, threshold: float | None = None) -> Recognizer:
    """Fabrique le backend demandé. `team` / `insightface` sont importés paresseusement (recette).

    Garde-fou : le backend `stub` (reconnaissance factice) n'est PAS une vraie reconnaissance ;
    on refuse de démarrer dessus par accident en recette/démo, sauf opt-in explicite
    `ALLOW_STUB_RECOGNIZER=1`. Les tests injectent directement un StubRecognizer (sans passer ici).
    """
    import os

    if backend == "stub":
        if os.getenv("ALLOW_STUB_RECOGNIZER", "") not in {"1", "true", "yes"}:
            raise RuntimeError(
                "RECOGNIZER_BACKEND=stub refusé (reconnaissance factice). "
                "Choisir 'team' ou 'insightface', ou poser ALLOW_STUB_RECOGNIZER=1 pour le dev."
            )
        return StubRecognizer(threshold if threshold is not None else 0.6)
    if backend == "insightface":  # pragma: no cover - validé en recette, deps non installées
        from face_id.backends.insightface_backend import InsightFaceRecognizer

        return InsightFaceRecognizer(threshold if threshold is not None else 0.65)
    if backend == "team":  # pragma: no cover - modèle de l'équipe (cf. INTEGRATION-ML.md)
        from face_id.backends.team_backend import TeamRecognizer

        return TeamRecognizer(threshold if threshold is not None else 0.6)
    raise ValueError(f"backend de reconnaissance inconnu: {backend!r}")
