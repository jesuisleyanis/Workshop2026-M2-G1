---
description: Scaffolde un nouveau composant du monorepo avec CDC, README, code, tests
argument-hint: <chemin du composant, ex. services/notifications>
---

Crée le squelette complet du composant **$ARGUMENTS** à la qualité « cas d'école » du projet.

Produis, dans le dossier du composant :

1. `CAHIER-DES-CHARGES.md` — rôle, périmètre, exigences du sujet couvertes (référence R#), interfaces consommées/exposées (pointant vers `docs/contracts.md`), contraintes de sécurité, critères d'acceptation.
2. `README.md` — architecture interne, arborescence, comment lancer, comment tester, variables d'environnement.
3. Le squelette de code conforme aux conventions de `CLAUDE.md` (FastAPI pour un service Python, React/Vite/TS pour un front).
4. Un dossier `tests/` avec au moins un test par règle métier / contrat d'interface, qui passe.
5. Un `Dockerfile` durci (slim, non-root, healthcheck) si c'est un service conteneurisé.

Puis ajoute la/les ligne(s) correspondante(s) dans `ROADMAP.md` et déclare le service dans `infra/compose/docker-compose.yml` si applicable.

Respecte strictement les contrats d'interfaces (`docs/contracts.md`) et la Definition of Done.
