"""Contrat que tout backend de reconnaissance doit respecter (consigne additionnelle 1).

Ce test verrouille l'interface `Recognizer` sur laquelle repose face-id. Il tourne ici sur
le StubRecognizer (déterministe, sans modèle). Quand le modèle de l'équipe est branché
(backend `team`, cf. INTEGRATION-ML.md), on ajoute un cas paramétré avec de VRAIES photos
(2 du même visage, 2 de visages différents) — seul cas qui valide la qualité de reconnaissance,
à jouer en recette.
"""

from __future__ import annotations

import pytest
from face_id.recognizer import NoFaceError, StubRecognizer, cosine_similarity


@pytest.fixture
def recognizer():
    return StubRecognizer()


def test_embed_returns_a_non_empty_fixed_length_float_vector(recognizer):
    a = recognizer.embed(b"image-A")
    b = recognizer.embed(b"image-B")
    assert a and all(isinstance(x, float) for x in a)
    assert len(a) == len(b)  # dimension stable d'un appel à l'autre


def test_same_image_yields_an_identical_embedding(recognizer):
    # Déterminisme : indispensable pour que la vérification 1:1 soit stable.
    assert recognizer.embed(b"same") == recognizer.embed(b"same")


def test_same_image_is_a_match_and_different_images_are_not(recognizer):
    same = cosine_similarity(recognizer.embed(b"alice"), recognizer.embed(b"alice"))
    diff = cosine_similarity(recognizer.embed(b"alice"), recognizer.embed(b"bob"))
    assert same >= recognizer.threshold  # même entrée -> correspondance
    assert diff < recognizer.threshold  # entrées différentes -> non-correspondance


def test_empty_image_raises_no_face_error(recognizer):
    with pytest.raises(NoFaceError):
        recognizer.embed(b"")


def test_recognizer_exposes_model_version_and_threshold(recognizer):
    assert isinstance(recognizer.model_version, str) and recognizer.model_version
    assert isinstance(recognizer.threshold, float)
