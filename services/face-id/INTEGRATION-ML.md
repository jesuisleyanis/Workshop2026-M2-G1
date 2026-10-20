# Brancher le modèle de reconnaissance de l'équipe sur `face-id`

> Le service `face-id` est complet (enrôlement 3 poses, vérification de séquence, chiffrement au
> repos, API, tests). Le modèle de reconnaissance est **isolé derrière l'interface `Recognizer`** :
> le modèle de l'équipe (Valentin, `face_recognition` / dlib) y est branché par le backend `team`
> (`src/face_id/backends/team_backend.py`) sans toucher aucun autre composant.

## Le contrat du modèle (v2)

Une classe qui expose **quatre choses** :

| Membre | Rôle |
|---|---|
| `model_version: str` | identifie la version du modèle (garde de compatibilité des gabarits : un changement impose un réenrôlement) |
| `threshold: float` | **distance maximale** (plus petit = plus proche) en deçà de laquelle deux visages sont « la même personne ». `team` : 0,6 |
| `analyze(image: bytes, *, precise: bool = False) -> FaceSample` | octets d'image → `FaceSample(embedding, pose)`. `embedding` = vecteur descripteur du visage ; `pose` ∈ `face` / `gauche` / `droite` ou `None` si indéterminée (zone morte). Lève `NoFaceError` (0 visage ou image illisible) ou `MultipleFacesError` (> 1 visage). `precise=True` (enrôlement) autorise un calcul plus coûteux (plus de *jitters*). |
| `distance(a, b) -> float` | distance entre deux embeddings (euclidienne pour dlib 128-d) |

> **RGPD :** on a besoin d'un **embedding par image**, pas d'une fonction « compare(imgA, imgB) » :
> seuls des gabarits (chiffrés) et des vignettes (chiffrées) sont conservés, jamais les photos pleine résolution.

### La pose

La pose est déduite des landmarks du visage (cf. `src/face_id/poses.py`, portée du notebook) :
`rotation = (x moyen du nez − x mâchoire gauche) / largeur mâchoire − 0,5`, puis
`|rot| ≤ 0,10` → `face`, `rot ≥ 0,15` → `gauche`, `rot ≤ −0,15` → `droite`, sinon `None`.
Un modèle qui fournit déjà la pose peut la renvoyer directement dans `FaceSample.pose`.

## Backend `team` (déjà branché)

`TeamRecognizer` (dlib 128-d via `face_recognition`) : `face_locations` → un seul visage exigé,
`face_landmarks` → pose, `face_encodings(num_jitters=5 si precise)` → embedding, `face_distance` →
distance. Dépendances dans `requirements-team.txt` (compilation de dlib : `cmake`, `build-essential`) ;
l'**image Docker** `services/face-id/Dockerfile` les installe et fixe `RECOGNIZER_BACKEND=team`.

Pour brancher **un autre modèle**, créer `backends/<nom>_backend.py` avec les quatre membres
ci-dessus, l'enregistrer dans `build_recognizer` (`recognizer.py`) et lancer avec `RECOGNIZER_BACKEND=<nom>`.
Si le modèle n'est pas importable en Python, un side-car HTTP (`HttpTeamRecognizer`, même interface,
`analyze` fait un POST) est possible.

## Vérifier que le branchement est bon

```bash
# 1) Contrat d'interface (structure, déterminisme, erreurs) — tourne sur le stub :
cd services/face-id && python -m pytest tests/test_recognizer_contract.py -q

# 2) Qualité réelle (recette, avec de vraies photos, backend team) :
#    3 poses de la MÊME personne  -> enrôlement 200 puis verify match
#    3 poses d'une personne DIFFÉRENTE -> verify match:false (face_mismatch dans les logs)
#    tête tournée du mauvais côté -> 422 wrong_pose (enrôlement) / match:false (verify)
#    -> calibrer FACE_MATCH_THRESHOLD sur ces mesures. Recette pas à pas : README.md.
```

## Ce que ça ne change pas

Rien côté `auth` (étapes), back-office, LED, contrats : `face-id /verify` répond `{match, model_version}`
quel que soit le modèle. Le reste de la chaîne tourne avec le backend `stub` (déterministe) ;
on bascule sur `team` quand l'image dlib est construite sur le PC Hôte.
