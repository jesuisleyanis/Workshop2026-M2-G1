"""Logique métier de l'enrôlement 3 poses et de la vérification de séquence.

Indépendante de HTTP et du stockage : prend un `Recognizer` et des octets d'image.

- `build_templates` : une image par pose (face, gauche, droite) -> un gabarit par pose. La série
  est refusée en bloc (toutes les anomalies sont remontées d'un coup, pour que l'opérateur
  reprenne seulement les poses fautives).
- `verify_sequence` : 3 images (une par pose, dans n'importe quel ordre) comparées au gabarit de
  la pose correspondante ; la pose détectée doit aussi être celle demandée (anti-rejeu d'une
  photo fixe : l'attaquant ne sait pas quelle pose sera demandée).
"""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO

from PIL import Image, ImageOps

from face_id.poses import POSES
from face_id.recognizer import MultipleFacesError, NoFaceError, Recognizer

# Motifs de refus d'enrôlement (contrat HTTP) : no_face | multiple_faces | wrong_pose |
# inconsistent | invalid_image | missing. `invalid_image` est produit par la couche HTTP.


@dataclass(frozen=True)
class PoseIssue:
    pose: str
    reason: str


class EnrollmentRejected(ValueError):
    """Série d'images refusée ; `issues` liste toutes les poses fautives et leur motif."""

    def __init__(self, issues: list[PoseIssue]) -> None:
        self.issues = issues
        super().__init__(", ".join(f"{i.pose}:{i.reason}" for i in issues))


def build_templates(recognizer: Recognizer, images: dict[str, bytes]) -> dict[str, list[float]]:
    """Gabarit par pose. Lève `EnrollmentRejected` avec TOUTES les anomalies trouvées.

    Pour chaque pose : image présente, un seul visage, pose détectée == pose attendue. Puis les
    gabarits `gauche` / `droite` doivent rester à distance <= seuil du gabarit `face` (même
    personne sur toute la série). Sans gabarit `face` exploitable, la cohérence n'est pas jugée.
    """
    templates: dict[str, list[float]] = {}
    issues: list[PoseIssue] = []
    for pose in POSES:
        image = images.get(pose)
        if not image:
            issues.append(PoseIssue(pose, "missing"))
            continue
        try:
            sample = recognizer.analyze(image, precise=True)
        except NoFaceError:
            issues.append(PoseIssue(pose, "no_face"))
            continue
        except MultipleFacesError:
            issues.append(PoseIssue(pose, "multiple_faces"))
            continue
        if sample.pose != pose:
            issues.append(PoseIssue(pose, "wrong_pose"))
            continue
        templates[pose] = sample.embedding

    reference = templates.get("face")
    if reference is not None:
        for pose in POSES:
            if pose == "face" or pose not in templates:
                continue
            if recognizer.distance(reference, templates[pose]) > recognizer.threshold:
                issues.append(PoseIssue(pose, "inconsistent"))
                del templates[pose]
    if issues:
        raise EnrollmentRejected(issues)
    return templates


def verify_sequence(
    recognizer: Recognizer,
    templates: dict[str, list[float]],
    frames: list[tuple[str, bytes]],
) -> tuple[bool, str]:
    """(match, motif). Motif : ok | no_face | multiple_faces | wrong_pose | face_mismatch | incomplete.

    Toutes les images sont évaluées (pas de court-circuit : durée indépendante de la position de
    l'échec) ; le motif renvoyé est celui de la première image fautive.
    """
    poses = [pose for pose, _ in frames]
    if sorted(poses) != sorted(POSES) or any(pose not in templates for pose in POSES):
        return False, "incomplete"
    first_failure: str | None = None
    for pose, image in frames:
        try:
            sample = recognizer.analyze(image)
        except NoFaceError:
            failure = "no_face"
        except MultipleFacesError:
            failure = "multiple_faces"
        else:
            if sample.pose != pose:
                failure = "wrong_pose"
            elif recognizer.distance(sample.embedding, templates[pose]) > recognizer.threshold:
                failure = "face_mismatch"
            else:
                continue
        first_failure = first_failure or failure
    return (True, "ok") if first_failure is None else (False, first_failure)


def thumbnail(image: bytes, max_side: int = 240) -> bytes:
    """Vignette JPEG (qualité 80) dont le plus grand côté est <= `max_side` (jamais agrandie).

    Lève ValueError si les octets ne sont pas une image décodable (pas de repli sur l'original :
    on ne stocke jamais une photo pleine résolution par accident).
    """
    try:
        with Image.open(BytesIO(image)) as im:
            im.load()
            oriented = ImageOps.exif_transpose(im)
            rgb = oriented.convert("RGB")
        rgb.thumbnail((max_side, max_side))
        out = BytesIO()
        rgb.save(out, format="JPEG", quality=80)
    except (OSError, ValueError, SyntaxError, Image.DecompressionBombError) as exc:
        raise ValueError("image illisible") from exc
    return out.getvalue()
