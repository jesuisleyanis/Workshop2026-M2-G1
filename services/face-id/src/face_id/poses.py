"""Logique de pose du visage (face / gauche / droite) à partir des points de repère.

Portée depuis le notebook de l'équipe : la rotation est la position relative du nez dans la
largeur de la mâchoire, recentrée sur 0 (nez au milieu => visage de face).
"""

from __future__ import annotations

#: Poses attendues à l'enrôlement (clés exactes, partagées avec le front et la base).
POSES: tuple[str, ...] = ("face", "gauche", "droite")

#: |rotation| <= SEUIL_FACE => « face ».
SEUIL_FACE = 0.10
#: rotation >= SEUIL_PROFIL => « gauche » ; rotation <= -SEUIL_PROFIL => « droite ».
SEUIL_PROFIL = 0.15


def rotation_from_points(
    jaw_left_x: float, jaw_right_x: float, nose_xs: list[float]
) -> float | None:
    """Rotation = (moyenne x du nez − x mâchoire gauche) / largeur mâchoire − 0.5.

    Renvoie None si la largeur de mâchoire est nulle/négative ou si le nez n'a aucun point.
    """
    width = jaw_right_x - jaw_left_x
    if width <= 0 or not nose_xs:
        return None
    return (sum(nose_xs) / len(nose_xs) - jaw_left_x) / width - 0.5


def pose_from_rotation(rotation: float | None) -> str | None:
    """Classe une rotation en pose ; None dans la zone morte (entre les deux seuils)."""
    if rotation is None:
        return None
    if abs(rotation) <= SEUIL_FACE:
        return "face"
    if rotation >= SEUIL_PROFIL:
        return "gauche"
    if rotation <= -SEUIL_PROFIL:
        return "droite"
    return None
