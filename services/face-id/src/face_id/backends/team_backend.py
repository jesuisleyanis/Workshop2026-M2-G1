"""Point de branchement du modèle de reconnaissance de l'équipe (consigne additionnelle 1).

Le service face-id dépend de l'interface `Recognizer` (face_id/recognizer.py), jamais d'un
modèle concret. Pour brancher le modèle d'un coéquipier, il suffit d'implémenter `embed()`
ci-dessous — tout le reste (vérification 1:1, enrôlement, RGPD, API, LED) est déjà en place.

Mode d'emploi complet : services/face-id/INTEGRATION-ML.md. Activation : RECOGNIZER_BACKEND=team.
"""

from __future__ import annotations

from face_id.recognizer import NoFaceError


class TeamRecognizer:  # pragma: no cover - rempli par l'équipe, validé en recette
    """Adaptateur du modèle de l'équipe vers l'interface `Recognizer`.

    Contrat à respecter (voir INTEGRATION-ML.md) :
      - `model_version` : identifie la version du modèle (pour la garde de compatibilité).
      - `threshold`     : seuil de similarité cosinus au-dessus duquel c'est une correspondance.
      - `embed(image)`  : octets d'une image -> vecteur de flottants (descripteur du visage).
                          Même visage -> vecteurs proches (cosinus élevé) ; visages différents
                          -> vecteurs éloignés. Lève NoFaceError si aucun visage exploitable.
                          RGPD : c'est CE vecteur qui est stocké, jamais l'image.
    """

    #: À remplacer par la vraie version du modèle de l'équipe.
    model_version = "team-model-TODO"

    def __init__(self, threshold: float = 0.5) -> None:
        self.threshold = threshold
        # TODO(équipe) : charger le modèle ici (une seule fois).
        #   ex. : self._model = charger_le_modele_de_lequipe()

    def embed(self, image: bytes) -> list[float]:
        if not image:
            raise NoFaceError("image vide")
        # TODO(équipe) : décoder l'image, détecter le visage, renvoyer le descripteur.
        #   visage = self._model.detecter(image)
        #   if visage is None: raise NoFaceError("aucun visage détecté")
        #   return [float(x) for x in self._model.embedding(visage)]
        raise NotImplementedError(
            "Brancher le modèle de l'équipe ici — voir services/face-id/INTEGRATION-ML.md"
        )
