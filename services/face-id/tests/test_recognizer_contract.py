"""Contrat que tout backend de reconnaissance doit respecter (Recognizer v2).

Ce test verrouille l'interface `Recognizer` sur laquelle repose face-id. Il tourne ici sur
le StubRecognizer (déterministe, sans modèle). Quand le modèle de l'équipe est branché
(backend `team`, cf. INTEGRATION-ML.md), on ajoute un cas paramétré avec de VRAIES photos
(2 du même visage, 2 de visages différents) — seul cas qui valide la qualité de reconnaissance,
à jouer en recette.
"""

from __future__ import annotations

import pytest
from face_id.recognizer import (
    FaceSample,
    MultipleFacesError,
    NoFaceError,
    StubRecognizer,
    build_recognizer,
    euclidean,
)


@pytest.fixture
def recognizer():
    return StubRecognizer()


def test_analyze_renvoie_un_echantillon_avec_embedding_et_pose(recognizer):
    s = recognizer.analyze(b"face|alice")
    assert isinstance(s, FaceSample)
    assert s.pose == "face"
    assert s.embedding and all(isinstance(x, float) for x in s.embedding)


def test_pose_lue_depuis_l_image(recognizer):
    assert recognizer.analyze(b"gauche|alice").pose == "gauche"
    assert recognizer.analyze(b"droite|alice").pose == "droite"
    assert recognizer.analyze(b"x|alice").pose is None


def test_embedding_deterministe_et_independant_de_la_pose(recognizer):
    a = recognizer.analyze(b"face|alice")
    assert a == recognizer.analyze(b"face|alice")
    assert a.embedding == recognizer.analyze(b"gauche|alice").embedding


def test_dimension_stable(recognizer):
    assert len(recognizer.analyze(b"face|alice").embedding) == len(
        recognizer.analyze(b"face|bob").embedding
    )


def test_meme_identite_pose_differente_distance_zero(recognizer):
    a = recognizer.analyze(b"face|alice").embedding
    b = recognizer.analyze(b"droite|alice").embedding
    assert recognizer.distance(a, b) == 0.0


def test_identites_differentes_distance_superieure_au_seuil(recognizer):
    a = recognizer.analyze(b"face|alice").embedding
    b = recognizer.analyze(b"face|bob").embedding
    assert recognizer.distance(a, b) > recognizer.threshold


def test_aucun_visage_leve_no_face_error(recognizer):
    with pytest.raises(NoFaceError):
        recognizer.analyze(b"none")
    with pytest.raises(NoFaceError):
        recognizer.analyze(b"")


def test_plusieurs_visages_leve_multiple_faces_error(recognizer):
    with pytest.raises(MultipleFacesError):
        recognizer.analyze(b"many")


def test_precise_accepte(recognizer):
    assert recognizer.analyze(b"face|alice", precise=True) == recognizer.analyze(b"face|alice")


def test_expose_model_version_et_seuil(recognizer):
    assert recognizer.model_version == "stub-2.0"
    assert recognizer.threshold == 0.6


def test_euclidean():
    assert euclidean([0.0, 0.0], [3.0, 4.0]) == 5.0
    with pytest.raises(ValueError):
        euclidean([0.0], [0.0, 1.0])


def test_build_recognizer_refuse_le_stub_sans_opt_in(monkeypatch):
    monkeypatch.delenv("ALLOW_STUB_RECOGNIZER", raising=False)
    with pytest.raises(RuntimeError):
        build_recognizer("stub")
    monkeypatch.setenv("ALLOW_STUB_RECOGNIZER", "1")
    assert isinstance(build_recognizer("stub"), StubRecognizer)
    assert build_recognizer("stub", 0.4).threshold == 0.4
    with pytest.raises(ValueError):
        build_recognizer("inconnu")
