"""Backend de reconnaissance réel : InsightFace `buffalo_s` (ONNX Runtime CPU).

Chargé uniquement quand RECOGNIZER_BACKEND=insightface (recette sur le PC Hôte). Les
dépendances (insightface, onnxruntime, numpy, opencv) ne sont PAS installées pour les tests —
le *plumbing* du service est couvert par le StubRecognizer. Ce module est donc hors couverture.
"""

from __future__ import annotations

from face_id.recognizer import NoFaceError


class InsightFaceRecognizer:  # pragma: no cover - validé en recette, deps non installées
    """Embeddings 512-d via InsightFace, similarité cosinus. Modèle `buffalo_s` (léger)."""

    model_version = "insightface-buffalo_s-1.0"

    def __init__(self, threshold: float = 0.35) -> None:
        self.threshold = threshold
        import numpy as np  # noqa: F401 - dépendance du backend réel
        from insightface.app import FaceAnalysis

        self._app = FaceAnalysis(name="buffalo_s", providers=["CPUExecutionProvider"])
        self._app.prepare(ctx_id=-1, det_size=(320, 320))

    def embed(self, image: bytes) -> list[float]:
        import cv2
        import numpy as np

        arr = cv2.imdecode(np.frombuffer(image, np.uint8), cv2.IMREAD_COLOR)
        if arr is None:
            raise NoFaceError("image illisible")
        faces = self._app.get(arr)
        if not faces:
            raise NoFaceError("aucun visage détecté")
        # Plus grand visage détecté (robuste aux visages de fond).
        face = max(faces, key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]))
        return [float(x) for x in face.normed_embedding]
