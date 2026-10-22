# Clip Chrono — `Workshop2026-M2-G1-VidChrono.mp4` (§7)

Clip de **≤ 60 s, en une seule prise sans coupe**, qui montre les 5 temps de la démo *Zero-Touch
Recovery* : `avant → attaque → détection → remédiation → après`, avec timeline et MTTD/MTTR sur le
dashboard. C'est un **enregistrement de la démo réelle** (stack levée), pas une animation : le clip est le
support filmé de la recette J4.

Ce dossier contient le **kit de production** (storyboard + script d'assemblage + validation). Le `.mp4`
lui-même se produit sur le **poste de démo** (stack `make up-full`, PC Attaquant), là où tournent la stack
et `ffmpeg`. Il est volontairement **non commité** (`Workshop2026-M2-G1-*` ignorés par git).

## Contenu

| Fichier | Rôle |
|---|---|
| [`storyboard.json`](storyboard.json) | **Contrat** machine-lisible : budget ≤ 60 s, 5 temps, légendes. Source de vérité. |
| [`storyboard.md`](storyboard.md) | Storyboard lisible : plan de cadrage, timecodes, message clé. |
| [`build_clip.sh`](build_clip.sh) | Recadre la prise brute au budget et **incruste les légendes** ; encode H.264 ; garde-fou de durée. |
| [`gen_ass.py`](gen_ass.py) | Génère la piste de légendes ASS depuis le storyboard (texte échappé, temps validés). Testable sans ffmpeg. |
| `scripts/tests/test_clip_chrono.py` | Vérifie le contrat (≤ 60 s, 5 temps ordonnés et contigus) et **exécute** `gen_ass.py`. |

## Produire le clip (poste de démo, J4)

### 1. Lever la stack et préparer la scène

```bash
make up-full          # stack + observabilité
make seed             # données fictives
```

Afficher le **dashboard ZTR** en plein écran et un terminal (bas-droite) prêt à lancer la démo. Préparer
l'attaque sur le **PC Attaquant** (voir `attacks/RUNBOOK-PC-ATTAQUANT.md`).

### 2. Enregistrer la prise unique (sans coupe)

> ⚠️ **Avant d'enregistrer : rien de sensible à l'écran.** La prise filme le dashboard et un terminal.
> Vérifier qu'aucun token, mot de passe ni contenu de `.env` n'y est affiché (le re-scan de secrets du
> packaging ne voit pas le contenu d'une vidéo). Enregistrer dans un dossier **hors dépôt** (`/tmp`) ; les
> `*.mkv`/`*.mp4`/`*.ass` sont de toute façon `.gitignore` et exclus de `Code.zip`.

Lancer la démo **juste après** l'enregistreur (le décalage du top « AVANT » sera ≈ 0), puis jouer les
5 temps d'une commande :

```bash
# Exemple d'enregistreur libre (Wayland) :
wf-recorder -f /tmp/prise_brute.mkv &   # ou OBS, ou `ffmpeg -f x11grab ...` sous X11
scripts/demo.sh service_flood           # joue avant→attaque→…→après (filmable en < 60 s)
kill -INT %1; wait %1                    # stoppe proprement l'enregistreur (finalise le conteneur)
```

Garder une prise **continue** qui couvre au moins 58 s à partir du top « AVANT ». Ne pas couper au montage :
`build_clip.sh` ne fait que **recadrer** (début + durée) et incruster le bandeau. Pour repérer le décalage
exact du top « AVANT » si l'enregistreur a démarré plus tôt, faire défiler avec `ffplay -ss <t> /tmp/prise_brute.mkv`.

### 3. Assembler le livrable

```bash
docs/dossier/clip/build_clip.sh /tmp/prise_brute.mkv 0
#   arg 1 : la prise brute       arg 2 : décalage du top « AVANT » dans la prise (s ou [hh:]mm:ss)
# -> Workshop2026-M2-G1-VidChrono.mp4 (racine du dépôt)
```

Le script incruste les légendes du storyboard, encode en H.264/`yuv420p` (lecture universelle), **refuse un
storyboard > 60 s avant d'encoder** et **échoue si la sortie est hors bornes** (trop longue, ou trop courte
si la prise ne couvre pas 58 s) ; le livrable n'est publié qu'**après** contrôle (sortie temporaire + `mv`).

> **Contrôle visuel obligatoire** après assemblage : relire le clip et vérifier que **chaque bandeau
> correspond à ce qui se passe à l'écran** (surtout « APRÈS — retour à la normale » : la transaction de
> contrôle doit vraiment repasser dans la prise). Sinon, recaler les `t_start/t_end` du storyboard ou
> refaire la prise — les légendes sont fixées dans le temps, elles n'observent pas le résultat.

## Vérifier (sans Docker ni ffmpeg)

Le kit est validé par un test qui ne demande ni la stack ni `ffmpeg` :

```bash
python3 -m pytest -q scripts/tests/test_clip_chrono.py
```

Il vérifie **le kit** (pas la vidéo finale, qui relève du contrôle visuel ci-dessus) : budget ≤ 60 s,
5 temps dans l'ordre `avant→…→après`, légendes contiguës dans le temps, et le générateur `gen_ass.py`
**exécuté** (une seule ligne `Dialogue` par temps, pas d'injection de balise ni de ligne ASS depuis le
JSON). Il contrôle aussi que `build_clip.sh` délègue à `gen_ass.py`, écrit le bon livrable, borne la durée
et ne publie qu'après contrôle (`OUT_TMP` + `mv`).

## Repli (si le 2e PC n'est pas prêt)

En secours uniquement, la démo peut être jouée en local avec le profil Compose `attack`
(`make attack SC=service_flood`) et filmée de la même façon — le profil `attack` **ne sert qu'au dev**
(cf. `CAHIER-DES-CHARGES.md §7`). La prise notée doit viser l'attaque depuis le vrai PC Attaquant.

## État

- Kit de production + contrat + validation : **livrés et testés** (voir le test ci-dessus).
- `Workshop2026-M2-G1-VidChrono.mp4` : **à enregistrer en recette J4** (stack levée + PC Attaquant).
  Les MTTD/MTTR visibles à l'écran sont aussi ceux qui remplacent les `[M]` du dossier (§11) et des slides.
