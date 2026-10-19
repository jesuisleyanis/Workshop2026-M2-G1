# Cahier des charges — ml/shared

**Pourquoi.** `docs/contracts.md §2` impose que « le `training` et le `detector` importent la même définition — jamais de
duplication ». Ce module est cette définition unique ; l'ordre des 9 features y est figé.

**Périmètre.**
- `FEATURE_NAMES` (ordre contractuel), `N_FEATURES`, conversions dict <-> vecteur, validation (longueur, valeurs finies).
- `zscores` avec plancher d'écart-type (`STD_FLOOR`) pour qu'une feature quasi constante en baseline ne produise pas de z absurdes.
- `top_features` : les features les plus déviantes, pour `features_top` de l'événement (§3).
- `classify_incident` : heuristique de routage vers `IncidentType` (service_flood / auth_abuse / web_attack / data_corruption / unknown).

**Hors périmètre / limites assumées.** `classify_incident` n'est **pas** de la détection (R8) : elle étiquette une anomalie
déjà décidée par le modèle. Elle retient le signal le plus fort ; un attaquant multi-vecteurs est étiqueté par sa composante
dominante, et sans signature claire on retombe sur `unknown` (dry-run + escalade, aucune action destructive — contrat §3).

**Critères d'acceptation.** Ordre/longueur conformes au contrat ; un test par signal dominant ; `data_corruption` jamais
confondu avec `service_flood` (contrat §3, sujet §2/§3.4) ; vecteur normal -> `unknown`.
