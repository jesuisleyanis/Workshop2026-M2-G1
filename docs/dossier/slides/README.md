# Support de présentation — `Workshop2026-M2-G1-Pres.pptx` (§7.2)

Support d'un oral de **10 minutes**, centré sur la **présentation de l'équipe**, avec deux schémas en appui.
11 slides : titre → l'équipe (6 cartes) → schéma d'architecture → démo en 5 temps → **une slide par membre**
(rôle, phrase d'accroche, 3 réalisations) → place à la démo. Notes du présentateur et minutage sur chaque slide.

Direction artistique : fond nuit profonde, code couleur de l'incident (menthe = sain/rétabli, corail = attaque,
ambre = détection, bleu = infrastructure), **ligne de pouls** du service en motif, avatars à initiales.
Animations : transitions **Morph** (repli en fondu sur les versions de PowerPoint qui ne l'ont pas : l'avatar d'un
membre glisse de la grille d'équipe vers sa slide), apparitions en cascade (fondu, balayage, flottement, zoom),
et sur le schéma d'architecture deux clics pour dérouler la boucle de reprise.

## Modifier le contenu

Tout le texte des slides membres est dans le tableau `TEAM` en tête de `build.js` (nom, initiales, rôle, couleur,
phrase d'accroche, 3 réalisations avec une icône [Lucide](https://lucide.dev/icons) `Lu…`). Ordre du tableau = ordre
de passage.

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
- Rendu des 11 slides relu (LibreOffice 26.8 + Carlito, métriquement identique à Calibri) : aucun débordement.
  Les surtitres en Consolas paraissent espacés sous LibreOffice (police de substitution) ; normal sous PowerPoint.
- **À vérifier dans PowerPoint** : les animations et le Morph (LibreOffice affiche l'état final des slides).
