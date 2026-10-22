# Support de présentation — `Workshop2026-M2-G1-Pres.pptx` (§7.2)

Support d'un oral de **10 minutes**, centré sur la **présentation de l'équipe**, avec deux schémas en appui.
5 slides : titre → l'équipe (6 cartes, **chacune avec les 3 réalisations du membre sur une seule slide**) →
schéma d'architecture → démo en 5 temps → place à la démo. Notes du présentateur et minutage sur chaque slide.

Direction artistique — un seul système visuel pour toutes les slides : fond nuit profonde, code couleur de
l'incident (menthe = sain/rétabli, corail = attaque, ambre = détection, bleu = infrastructure).
- **Grille** commune : même marge, même en-tête (surtitre + titre), même pied ; constantes `X0`, `CW`, `TOP`.
- **Carte** unique (`card`) : panneau sobre + onglet de couleur en haut à gauche — membres, nœuds d'architecture,
  étapes de la démo. **Anneau** unique (`ring`) pour les avatars à initiales et les numéros d'étape.
- **Ligne de pouls** réservée aux deux slides « héros » (ouverture et clôture, au même endroit, en miroir).

Animations sobres, une seule règle : **transition en fondu rapide**, et **un seul effet d'entrée, le fondu**,
appliqué **par bloc** (une carte entière apparaît d'un coup), en cascade régulière de 100 ms dans le sens de lecture.
- Ouverture et clôture : statiques (seul le fondu de transition).
- Équipe : les 6 cartes apparaissent l'une après l'autre (≈ 0,9 s au total).
- Architecture : chemin métier affiché d'emblée ; clic 1 = boucle de reprise, clic 2 = action du moteur.
- Démo : les 5 étapes (numéro + carte) de gauche à droite (≈ 0,8 s).

## Modifier le contenu

Tout le texte de l'équipe est dans le tableau `TEAM` en tête de `build.js` (nom, initiales, rôle, couleur,
phrase d'accroche, 3 réalisations avec une icône [Lucide](https://lucide.dev/icons) `Lu…`). Sur la slide d'équipe,
chaque réalisation affiche son titre et son détail ; la phrase d'accroche passe dans les notes du présentateur.
Ordre du tableau = ordre d'affichage des cartes.

Le rythme se règle avec deux constantes de `build.js` : `FADE` (durée d'un fondu, 400 ms) et `STEP` (décalage
entre deux blocs, 100 ms).

## Générer

```bash
cd docs/dossier/slides && npm install && node build.js      # -> ../../../Workshop2026-M2-G1-Pres.pptx
```

| Fichier | Rôle |
|---|---|
| `build.js` | contenu et mise en page (`pptxgenjs` : thème, 2 layouts, sections, placeholders) |
| `assets.js` | visuels générés à la volée : fonds, ligne de pouls, halos, icônes (`react-icons` + `sharp`) |
| `apply_theme.js` | écrit les couleurs du thème dans le fichier |
| `animate.js` | injecte transitions et animations dans l'OOXML (pptxgenjs ne les écrit pas) ; échoue si une forme animée est introuvable |

Le `.pptx` est écrit à la racine du dépôt (ignoré par git), puis copié dans `Workshop2026-M2-G1/` pour la remise.

## Contrôles

- Validation OOXML (`validate.py` de la skill pptx : schéma, relations, slides) : OK au 22 octobre 2026.
- Rendu des 5 slides relu (LibreOffice + Carlito, métriquement identique à Calibri) : aucun débordement.
  Les surtitres en Consolas paraissent espacés sous LibreOffice (police de substitution) ; normal sous PowerPoint.
- **À vérifier dans PowerPoint** : les animations (LibreOffice affiche l'état final des slides).
