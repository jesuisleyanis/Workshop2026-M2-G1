# docs/dossier — Dossier d'ingénierie et de gouvernance (§7.1) et support de présentation (§7.2)

| Fichier | Rôle |
|---|---|
| `dossier.md` | **Source** du dossier (Markdown, 8–12 pages hors annexes). C'est ici qu'on rédige. |
| `style.css` | Mise en page A4 (impression). |
| `build.sh` | Export `dossier.md` → `dossier.html` → **`Workshop2026-M2-G1-Dossier.pdf`** (racine du dépôt). |
| `slides/` | Source et export du support **`Workshop2026-M2-G1-Pres.pptx`** (voir `slides/README.md`). |

## Générer le PDF

```bash
pip install markdown                 # ou dans le venv du projet (uv pip install markdown)
docs/dossier/build.sh                # exige Google Chrome / Chromium (mode headless)
# -> Workshop2026-M2-G1-Dossier.pdf + nombre de pages (pdfinfo si présent)
docs/dossier/build.sh --html-only    # sans Chrome : ouvrir dossier.html et « Imprimer en PDF » (A4, sans en-têtes)
```

`PYTHON=/chemin/python docs/dossier/build.sh` pour choisir l'interpréteur. Le PDF et le HTML générés ne sont pas commités
(`Workshop2026-M2-G1-*` ignorés par git) ; on régénère au gel du code.

## Règles de rédaction

- Le dossier **renvoie au dépôt** pour le détail (annexe A : où vérifier chaque affirmation) ; il ne duplique pas
  `docs/ebios-rm.md`, `docs/pca-pra.md`, `docs/nis2-dora.md`, il les synthétise.
- Pas de surclaim : ce qui n'est pas mesuré est marqué **[M]** (tableau des MTTD/MTTR du §8, à remplir après la recette J4).
- Cohérence avec le code : proxy Docker = HAProxy (pas Tecnativa), métriques et événements = noms du contrat,
  compteurs de tests = ceux de `make test`.
- Les lignes « à compléter » du §13 (contributions) sont à renseigner par l'équipe avant la remise.
- Contrôle de pagination après chaque modification : `build.sh` affiche le nombre de pages (page de garde et annexes comprises :
  viser ≤ 12 pages au total avec ~10 pages de corps).
