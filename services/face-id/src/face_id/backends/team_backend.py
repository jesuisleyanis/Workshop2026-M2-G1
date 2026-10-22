"""Backend `team` : modèle de l'équipe (notebook) basé sur `face_recognition` (dlib).

Activation : RECOGNIZER_BACKEND=team. Les dépendances (`face_recognition`, `dlib`, numpy) sont
importées paresseusement dans la classe : le paquet reste importable sans elles (tests, CI).
Mode d'emploi : services/face-id/INTEGRATION-ML.md.
"""

from __future__ import annotations

import os
from io import BytesIO

from face_id.poses import pose_from_rotation, rotation_from_points
from face_id.recognizer import FaceSample, MultipleFacesError, NoFaceError


class TeamRecognizer:  # pragma: no cover - validé en recette, dlib non installé pour les tests
    """Gabarits 128-d dlib, distance euclidienne, pose déduite des landmarks du visage."""

    model_version = "team-dlib-face_recognition-1.3.0"

    def __init__(self, threshold: float = 0.6, upsample: int | None = None) -> None:
        self.threshold = threshold
        # Levier de recette (latence) : nombre de suréchantillonnages du détecteur HOG de dlib.
        # 1 = défaut dlib ; 0 suffit pour un visage proche sur une capture 640 px et divise le
        # temps de détection (~x4). Variable FACE_DETECT_UPSAMPLE ; ne change pas les gabarits.
        if upsample is None:
            upsample = int(os.getenv("FACE_DETECT_UPSAMPLE", "1"))
        self.upsample = max(0, upsample)
        import face_recognition  # échoue tôt si la dépendance manque

        self._fr = face_recognition

    def analyze(self, image: bytes, *, precise: bool = False) -> FaceSample:
        fr = self._fr
        try:
            img = fr.load_image_file(BytesIO(image))
        except Exception as exc:  # image illisible = pas de visage exploitable
            raise NoFaceError("image illisible") from exc
        locations = fr.face_locations(img, number_of_times_to_upsample=self.upsample)
        if not locations:
            raise NoFaceError("aucun visage détecté")
        if len(locations) > 1:
            raise MultipleFacesError(f"{len(locations)} visages détectés")
        pose = None
        landmarks = fr.face_landmarks(img, locations)
        if landmarks:
            chin = landmarks[0]["chin"]
            nose_tip = landmarks[0]["nose_tip"]
            rotation = rotation_from_points(chin[0][0], chin[-1][0], [p[0] for p in nose_tip])
            pose = pose_from_rotation(rotation)
        encodings = fr.face_encodings(img, [locations[0]], num_jitters=5 if precise else 1)
        return FaceSample([float(x) for x in encodings[0]], pose)

    def distance(self, a: list[float], b: list[float]) -> float:
        import numpy as np

        return float(self._fr.face_distance(np.array([a]), np.array(b))[0])
