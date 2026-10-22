"""Tests de la logique de pose (rotation du visage -> face / gauche / droite)."""

from __future__ import annotations

import pytest
from face_id.poses import POSES, SEUIL_FACE, SEUIL_PROFIL, pose_from_rotation, rotation_from_points


def test_constantes_du_contrat():
    assert POSES == ("face", "gauche", "droite")
    assert SEUIL_FACE == 0.10
    assert SEUIL_PROFIL == 0.15


@pytest.mark.parametrize(
    ("rotation", "attendu"),
    [
        (0.0, "face"),
        (0.10, "face"),
        (-0.10, "face"),
        (0.2, "gauche"),
        (0.15, "gauche"),
        (-0.2, "droite"),
        (-0.15, "droite"),
        (0.12, None),
        (-0.12, None),
        (None, None),
    ],
)
def test_pose_from_rotation(rotation, attendu):
    assert pose_from_rotation(rotation) == attendu


def test_rotation_centree_donne_zero():
    # nez pile au milieu de la mâchoire -> rotation 0
    assert rotation_from_points(0.0, 100.0, [50.0, 50.0]) == pytest.approx(0.0)


def test_rotation_utilise_la_moyenne_des_points_du_nez():
    # moyenne = 70 -> 70/100 - 0.5 = 0.2
    assert rotation_from_points(0.0, 100.0, [60.0, 80.0]) == pytest.approx(0.2)


def test_rotation_negative_quand_nez_a_gauche():
    assert rotation_from_points(10.0, 110.0, [30.0]) == pytest.approx(-0.3)


@pytest.mark.parametrize("gauche_x,droite_x", [(100.0, 100.0), (100.0, 50.0)])
def test_largeur_non_positive_donne_none(gauche_x, droite_x):
    assert rotation_from_points(gauche_x, droite_x, [75.0]) is None


def test_points_du_nez_vides_donne_none():
    assert rotation_from_points(0.0, 100.0, []) is None
