# Gel du code — J4 17h (checklist de remise)

> Procédure de **gel du code** (sujet §7 / [ROADMAP](../ROADMAP.md) J4). À jouer d'un bloc à 17h sur une
> machine **avec Docker** (le poste de dev n'en a pas). But : figer une version remise reproductible, sans
> secret, avec tous les livrables régénérés à partir du même commit.

## 0. Pré-vol (la veille / le matin)

- [ ] `ROADMAP.md` à jour : plus aucune ligne ⬜ sur le périmètre remis (ou reportée explicitement ⏭️).
- [ ] Les `[M]` du dossier (§11) et des slides (slide 8) **remplacés** par les MTTD/MTTR mesurés en recette.
- [ ] Clip Chrono enregistré (`docs/dossier/clip/README.md`) → `Workshop2026-M2-G1-VidChrono.mp4`.

## 1. Tests verts (Definition of Done)

```bash
make test            # 12 composants Python + front + dashboard, tout vert
```

- [ ] `make test` = OK (aucun composant rouge). Procédure venv : `README.md § Tests`.
- [ ] Lint propre : `ruff check .` (hook pre-commit joué).

## 2. Recette live (stack levée)

```bash
make up-full && make seed
make demo SC=service_flood     # les 5 temps s'enchaînent
make verify                    # transaction de contrôle -> exit 0
```

- [ ] Chaîne `avant → attaque → détection → remédiation → après` rejouée **sans intervention humaine**.
- [ ] MTTD/MTTR relevés et reportés (dossier §11, slides, clip).
- [ ] `make down` propre.

## 3. Arbre propre, PUIS régénération des livrables (même commit)

L'archive est construite depuis l'arbre de travail : il doit être **propre avant** de régénérer, sinon le
zip ne correspond pas au commit tagué.

```bash
git switch main && git pull --ff-only
test -z "$(git status --porcelain --untracked-files=no)" || { echo "arbre sale — commit/clean avant de geler"; exit 1; }
git rev-parse HEAD                               # noter le commit (doit rester HEAD après régénération)

cd docs/dossier         && ./build.sh            # -> Workshop2026-M2-G1-Dossier.pdf
cd docs/dossier/slides  && node build.js         # -> Workshop2026-M2-G1-Pres.pptx
scripts/package_deliverables.sh                  # -> Workshop2026-M2-G1-Code.zip (audit + re-scan secrets)
```

- [ ] Arbre propre **avant** régénération (`git status --porcelain` vide hors livrables ignorés).
- [ ] `Workshop2026-M2-G1-Dossier.pdf` (8–12 p hors annexes) régénéré.
- [ ] `Workshop2026-M2-G1-Pres.pptx` régénéré, relu dans PowerPoint/LibreOffice.
- [ ] `Workshop2026-M2-G1-VidChrono.mp4` ≤ 60 s, sans coupe, **relu** (chaque bandeau colle à l'écran — cf. `docs/dossier/clip/README.md`).
- [ ] `Workshop2026-M2-G1-Code.zip` : **aucun secret**, aucune prise brute (le script exclut `*.mkv/*.mp4/*.mov/*.ass` et re-scanne noms + contenu).
- [ ] Clé age de démo prête **hors archive**.

## 4. Gel Git (17h précises)

```bash
git rev-parse HEAD               # identique au commit noté en §3 (sinon régénérer)
git tag -a freeze-j4 -m "Gel du code J4 17h — remise Workshop2026-M2-G1"
git push origin main freeze-j4   # pousse main + CE tag (pas --tags : évite les tags de test)
```

- [ ] `HEAD` inchangé depuis la régénération (les livrables viennent bien de ce commit).
- [ ] Tag `freeze-j4` posé et poussé (push ciblé, pas `--tags`).
- [ ] **Après le tag : plus aucun commit** sur le périmètre remis (sauf correctif bloquant tracé dans la ROADMAP).

## Garde-fous

- Les livrables `Workshop2026-M2-G1-*` sont **ignorés par git** : on les régénère, on ne les commite pas.
- Un secret déchiffré ne doit jamais entrer dans l'archive : `package_deliverables.sh` échoue (fail closed)
  s'il en détecte un (nom **ou** contenu).
- Si un test est rouge ou la recette échoue : **on ne gèle pas** — on corrige ou on reporte la ligne (⏭️).
