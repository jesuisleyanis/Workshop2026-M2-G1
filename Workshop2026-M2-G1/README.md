# Workshop2026-M2-G1 — dossier de remise (sujet §7)

Les rendus impératifs, sous les noms exigés par le sujet. Ils sont **générés depuis le dépôt** puis copiés ici
et commités pour que toute l'équipe ait la même version ; ne pas les éditer à la main.

| Fichier | Source | Régénérer |
|---|---|---|
| `Workshop2026-M2-G1-Dossier.pdf` | `docs/dossier/dossier.md` | `docs/dossier/build.sh` |
| `Workshop2026-M2-G1-Pres.pptx` | `docs/dossier/slides/build.js` | `cd docs/dossier/slides && node build.js` |
| `Workshop2026-M2-G1-VidChrono.mp4` | montage des captures de la recette J4 (PC Attaquant, SOC, back-office, module IoT) : 59 s, 1080p, sans son | montage ffmpeg hors dépôt, rushes non versionnés (le kit prise unique reste dans `docs/dossier/clip/`) |
| `Workshop2026-M2-G1-Code.zip` | le dépôt (sans secrets, sans ce dossier) | `scripts/package_deliverables.sh` |

Les générateurs écrivent à la racine du dépôt (sorties de travail, ignorées par git) ; on copie ensuite ici :

```bash
cp Workshop2026-M2-G1-{Dossier.pdf,Pres.pptx,Code.zip} Workshop2026-M2-G1/
```

État : voir la ligne « Gel du code 17h » de `ROADMAP.md` et `docs/FREEZE-J4.md`. Les `[M]` du dossier et des slides
attendent les p95 de la recette J4.
