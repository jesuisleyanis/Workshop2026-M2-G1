# Support de présentation — `Workshop2026-M2-G1-Pres.pptx` (§7.2)

Pitch court (~5 min, 10 slides) qui **facilite la compréhension** de la solution sans se substituer à la démo :
ouverture → critère unique → architecture → démo en 5 temps → détection ML → remédiation et privilèges →
Red Team / défense → résultats → gouvernance (EBIOS, PCA/PRA, DORA) → limites, contributions, place à la démo.
Notes du présentateur sur chaque slide. Contenu aligné sur `../dossier.md`.

## Générer

```bash
cd docs/dossier/slides && npm install && node build.js      # -> ../../../Workshop2026-M2-G1-Pres.pptx
```

`build.js` utilise `pptxgenjs` (deck structuré : thème, 2 layouts, sections, placeholders) et `apply_theme.js`
(écrit les couleurs du thème dans le fichier). Le `.pptx` généré n'est pas commité (`Workshop2026-M2-G1-*` ignorés).

## Contrôles effectués / à faire

- Validation OOXML (schémas, relations, graphique natif) : OK au 19 octobre 2026.
- Contrôle géométrique des débordements de texte (python-pptx, heuristique) : OK.
- **Relecture visuelle dans PowerPoint ou LibreOffice à faire** (non disponible sur le poste de génération) :
  vérifier l'ajustement des textes, puis remplacer les `[M]` (slide 8) par les mesures de recette et compléter
  les contributions (slide 10) avant la remise.
