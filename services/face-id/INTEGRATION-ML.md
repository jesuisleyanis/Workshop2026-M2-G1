# Brancher le modèle de reconnaissance de l'équipe sur `face-id`

> Le service `face-id` est déjà complet (vérification 1:1, enrôlement, RGPD, API, LED, 15 tests).
> Le modèle de reconnaissance est **isolé derrière l'interface `Recognizer`** : y brancher le
> modèle d'un coéquipier ne touche **aucun** autre composant. Objectif : handoff en ~15 min.

## Ce dont on a besoin du modèle (le contrat)

Une classe qui expose **trois choses** (voir le gabarit `src/face_id/backends/team_backend.py`) :

| Membre | Rôle |
|---|---|
| `model_version: str` | identifie la version du modèle (garde de compatibilité des embeddings) |
| `threshold: float` | seuil de **similarité cosinus** au-dessus duquel deux visages sont « la même personne » |
| `embed(image: bytes) -> list[float]` | octets d'une image → **vecteur descripteur** du visage. Même personne → vecteurs proches (cosinus élevé) ; personnes différentes → vecteurs éloignés. Lève `NoFaceError` si aucun visage exploitable. |

**C'est tout.** `face-id` se charge du reste : il stocke le vecteur (jamais l'image — RGPD), compare en cosinus, applique le seuil, renvoie `match`/`score`, et gère enrôlement/révocation/API/LED.

> **Important (RGPD) :** on a besoin d'un **embedding par image** (un vecteur), pas d'une fonction
> « compare(imgA, imgB) ». C'est ce qui permet de ne stocker qu'un vecteur à l'enrôlement et de
> ne **jamais** conserver la photo. Si le modèle de l'équipe ne sait faire que du pairwise compare
> ou renvoie un label de classe, **dis-le-moi** : on adapte l'interface (et on en discute l'impact RGPD).

## Deux façons de brancher

### A. En Python, dans le process (le plus simple si le modèle est une lib Python)
1. Remplir `embed()` et `model_version` dans `src/face_id/backends/team_backend.py` (TODO balisés).
2. Ajouter les dépendances du modèle dans `requirements.txt`.
3. Lancer avec `RECOGNIZER_BACKEND=team` (et éventuellement `FACE_MATCH_THRESHOLD=…`).

### B. En side-car HTTP (si le modèle n'est pas importable en Python / autre techno)
Le modèle tourne comme un petit service ; `face-id` l'appelle. On écrit alors un
`HttpTeamRecognizer` (même interface, `embed` fait un POST). Dis-moi si c'est ce cas, je le fournis.

## Vérifier que le branchement est bon

```bash
# 1) Contrat d'interface (structure, déterminisme, NoFaceError) :
PYTHONPATH=services/face-id/src python -m pytest services/face-id/tests/test_recognizer_contract.py -q

# 2) Qualité réelle (recette, avec de vraies photos) :
#    2 photos de la MÊME personne  -> match (cosinus >= threshold)
#    2 photos de personnes DIFFÉRENTES -> no-match (cosinus < threshold)
#    -> calibrer threshold sur ces mesures.
```

## Ce que ça ne change pas

Rien côté `auth` (étapes), back-office, LED, contrats : `face-id /verify` garde la même réponse
`{match, score, threshold, model_version}`. Le reste de la chaîne tourne déjà aujourd'hui avec le
backend `stub` (déterministe) ; on bascule sur `team` quand le modèle est prêt.
