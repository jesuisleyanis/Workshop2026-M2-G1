# CLAUDE.md — PROJECT RESILIENCE-ALPHA (Workshop2026-M2-G1)

Guide d'agent pour ce monorepo. Lis-le avant toute contribution. Les détails par composant sont dans chaque `*/CAHIER-DES-CHARGES.md` et `*/README.md`.

## Ce qu'est ce projet

Démonstrateur de **cyber-résilience et reprise autonome** (*Zero-Touch Recovery*). Une plateforme de paiement **fictive** conteneurisée est attaquée depuis un PC distinct ; un modèle ML détecte l'anomalie, un moteur de remédiation corrige **automatiquement**, et une transaction de vérification prouve le retour à la normale — **sans intervention humaine**.

Toutes les données sont fictives. Le périmètre offensif est strictement limité au SI du projet (réseau `RESILIENCE-G1`). C'est un travail de sécurité **défensive / Blue Team** à visée pédagogique.

**Document contractuel central : [`docs/contracts.md`](docs/contracts.md)** — logs, métriques, événement d'anomalie, table de décision. Tout composant qui s'intègre DOIT le respecter.
**Suivi : [`ROADMAP.md`](ROADMAP.md). Cadrage global : [`CAHIER-DES-CHARGES.md`](CAHIER-DES-CHARGES.md).**

## Le flow de travail (NON négociable)

Pour **chaque** tâche, dans cet ordre — c'est la Definition of Done :

1. **On code** — conforme aux contrats d'interfaces. Petit, lisible, dans le style du voisinage.
2. **On écrit les tests** — unitaires au minimum ; e2e si la tâche touche la chaîne de démo. Ils doivent être **verts** avant de considérer la tâche finie.
3. **On écrit / met à jour la doc** — le `README.md` et/ou `CAHIER-DES-CHARGES.md` du composant, et la doc transverse si une interface change.
4. **On update l'avancement** — la ligne correspondante dans [`ROADMAP.md`](ROADMAP.md) (statut + preuve : commit ou test).

La commande `/avancer` guide ce cycle. Ne jamais marquer ✅ une tâche dont les tests ne passent pas ou dont la doc n'est pas à jour.

## Conventions

- **Langage backend :** Python 3.12 + FastAPI partout. `ruff` (lint+format), `mypy` quand c'est utile. Env géré avec `uv` ou `venv` + `requirements.txt` par service.
- **Front :** React + Vite + TypeScript + Tailwind. ESLint. Tests avec Vitest + Testing Library.
- **Tests Python :** `pytest`. Viser le chemin critique, pas 100 % de couverture pour la couverture. Un test par règle métier et par contrat d'interface.
- **Logs :** format JSON du contrat (`docs/contracts.md §1`). Jamais de `print`.
- **Métriques :** préfixe `resilience_`, noms figés dans le contrat.
- **Secrets :** jamais en clair, jamais commités. SOPS + age (`security/sops`). La clé age privée reste hors git. `gitleaks` en pre-commit.
- **Commits :** format `type(scope): sujet` (`feat(payment-api): ...`, `test(detector): ...`, `docs(ebios): ...`). Un commit = une unité cohérente code+test+doc quand c'est possible.
- **Chaque composant** a : `CAHIER-DES-CHARGES.md` (quoi + pourquoi), `README.md` (comment lancer/tester), du code, des tests.

## Sécurité — points durs (sondés par le jury)

- Le **moteur de remédiation** ne touche jamais le socket Docker brut : il passe par `docker-socket-proxy` avec verbes limités. Son API est authentifiée (token SOPS) et **non exposée** sur le réseau `edge`. Voir `remediation/CAHIER-DES-CHARGES.md`.
- **Seul le WAF** est exposé (80/443). DB, secrets, API internes, management : réseaux `data`/`app`/`obs` internes, jamais `0.0.0.0`.
- Conteneurs durcis : image slim, utilisateur non-root, `cap_drop: ALL`, `read_only` quand possible, limites CPU/RAM, healthchecks.
- Distinguer **restauration de disponibilité** (`service_flood`) et **correction de compromission/corruption** (`data_corruption`) — ce sont des réponses différentes (sujet §2, §3.4).

## Ne pas faire

- Pas de CI pour l'instant (décision équipe : on l'ajoute en fin de sprint pour ne pas ralentir les push). Les tests se lancent en local.
- Pas de réduction de la détection à des `if` codés en dur : la décision vient du **modèle ML** (`docs/contracts.md §3`).
- Pas d'intervention humaine dans la boucle de reprise de la démo (sanction ND/0 du jury).
- Pas d'action offensive hors du réseau du projet.

## Commandes utiles

```bash
make up           # lève la stack (profil démo minimal)
make up-full      # stack complète avec observabilité
make down         # arrête tout
make seed         # peuple les données fictives
make verify       # scripts/verify_tx — transaction de contrôle (0 = OK)
make demo         # joue les 5 temps de la démo
make test         # lance tous les tests (python + front)
make attack SC=<scenario>   # lance un scénario (dev ; en démo : depuis le PC Attaquant)
```

## Structure

```
services/{payment-api,auth,front}   microservices métier
ml/{collector,training,detector}    détection d'anomalies (AIOps)
remediation/                        moteur de décision + actions
dashboard/                          supervision React/Tailwind
assistant/                          RAG Ollama/LangChain
security/{sops,waf,hardening}       secrets, WAF, durcissement
attacks/                            scénarios Red Team (PC Attaquant)
infra/{compose,prometheus,loki,promtail,grafana,alertmanager,ansible}
scripts/                            demo.sh, verify_tx, seed.py, package_deliverables.sh
docs/                               contracts, architecture, ebios-rm, pca-pra, nis2-dora, dossier
tests/e2e/                          rejeu des scénarios de bout en bout
```
