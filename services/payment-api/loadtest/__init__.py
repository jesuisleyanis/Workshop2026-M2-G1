"""Harnais de test de charge du service payment-api.

Expose `loadgen` : construction d'une cible (app in-process ou URL live),
génération de charge en boucle fermée, agrégation des latences/débit, portes SLO.
"""
