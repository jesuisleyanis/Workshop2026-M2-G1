"""Service de reconnaissance faciale 1:1 (consigne additionnelle 1).

Vérifie qu'un visage correspond à un identifiant (vérification 1:1), gère l'enrôlement
des habilitations biométriques. RGPD : stocke uniquement l'embedding (vecteur), jamais l'image.
"""

SERVICE_NAME = "face-id"
