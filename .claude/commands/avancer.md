---
description: Exécute le flow de Definition of Done sur une tâche (code → tests → doc → avancement)
argument-hint: <composant ou tâche, ex. "payment-api: route /transactions">
---

Tu travailles sur la tâche : **$ARGUMENTS**

Applique le flow non négociable du projet (voir `CLAUDE.md` et `CAHIER-DES-CHARGES.md §5`), dans cet ordre, sans en sauter une étape :

1. **Situer** — lis le `CAHIER-DES-CHARGES.md` et le `README.md` du composant concerné, et `docs/contracts.md` pour les interfaces touchées. Repère la ligne correspondante dans `ROADMAP.md`.
2. **Coder** — implémente la tâche, conforme aux contrats d'interfaces. Reste dans le style du code voisin.
3. **Tester** — écris/complète les tests (`pytest` ou `vitest`) et **lance-les**. Ne continue pas tant qu'ils ne sont pas verts. Montre la sortie des tests.
4. **Documenter** — mets à jour le `README.md`/`CAHIER-DES-CHARGES.md` du composant et la doc transverse si une interface a changé.
5. **Avancer** — mets à jour la ligne de `ROADMAP.md` (statut ✅/🟨, propriétaire, preuve = fichier de test ou commit), et la barre d'avancement de la phase si pertinent.

Termine par un résumé court : ce qui est fait, résultat des tests, fichiers doc touchés, ligne de roadmap mise à jour. Ne marque jamais ✅ une tâche dont les tests échouent ou dont la doc n'est pas à jour.
