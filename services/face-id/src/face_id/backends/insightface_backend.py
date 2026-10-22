"""Backend de reconnaissance réel : InsightFace `buffalo_s` (ONNX Runtime CPU).

Chargé uniquement quand RECOGNIZER_BACKEND=insightface (recette sur le PC Hôte). Les
dépendances (insightface, onnxruntime, numpy, opencv) ne sont PAS installées pour les tests —
le *plumbing* du service est couvert par le StubRecognizer. Ce module est donc hors couverture.
"""

from __future__ import annotations

from face_id.poses import pose_from_rotation, rotation_from_points
from face_id.recognizer import FaceSample, MultipleFacesError, NoFaceError


class InsightFaceRecognizer:  # pragma: no cover - validé en recette, deps non installées
    """Embeddings 512-d via InsightFace ; distance = 1 - similarité cosinus."""

    model_version = "insightface-buffalo_s-2.0"

    def __init__(self, threshold: float = 0.65) -> None:
        self.threshold = threshold
        import numpy as np  # noqa: F401 - dépendance du backend réel
        from insightface.app import FaceAnalysis

        self._app = FaceAnalysis(name="buffalo_s", providers=["CPUExecutionProvider"])
        self._app.prepare(ctx_id=-1, det_size=(320, 320))

    def analyze(self, image: bytes, *, precise: bool = False) -> FaceSample:
        import cv2
        import numpy as np

        arr = cv2.imdecode(np.frombuffer(image, np.uint8), cv2.IMREAD_COLOR)
        if arr is None:
            raise NoFaceError("image illisible")
        faces = self._app.get(arr)
        if not faces:
            raise NoFaceError("aucun visage détecté")
        if len(faces) > 1:
            raise MultipleFacesError(f"{len(faces)} visages détectés")
        face = faces[0]
        # kps = 5 points (œil gauche, œil droit, nez, bouche g., bouche d.) : le nez est situé
        # relativement à l'écart des yeux, mêmes seuils que le backend `team`.
        kps = face.kps
        rotation = rotation_from_points(float(kps[0][0]), float(kps[1][0]), [float(kps[2][0])])
        return FaceSample([float(x) for x in face.normed_embedding], pose_from_rotation(rotation))

    def distance(self, a: list[float], b: list[float]) -> float:
        import numpy as np

        va, vb = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
        denom = float(np.linalg.norm(va) * np.linalg.norm(vb))
        if denom == 0.0:
            return 1.0
        return 1.0 - float(np.dot(va, vb)) / denom
