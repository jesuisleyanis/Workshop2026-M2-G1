# Plan — fiabiliser et accélérer le lancement de la stack

Statut : **lots 0 à 4 appliqués** sur la branche `perf/lancement-stack` (2026-10-20), sauf C7 (décision équipe). Suivi : `ROADMAP.md` § Lancement de la stack. Chaque lot suit la Definition of Done du projet :
code → tests → doc → ligne `ROADMAP.md`. Référence des commandes : [`commandes.md`](commandes.md).

Les gains annoncés sont **estimés à la lecture** des fichiers (tailles mesurées avec `du`), pas chronométrés.
Le lot 0 prévoit la mesure avant/après.

---

## Constats

| # | Constat | Où | Impact |
|---|---|---|---|
| C1 | `collector` et `detector` sont en `profiles: [ml]`, mais aucune cible `make` n'active `ml`. `make down` non plus. | `docker-compose.yml:210,223`, `Makefile:48-60` | **Bloquant démo** : la boucle Zero-Touch ne détecte rien après `make up` ; un detector lancé à la main n'est jamais arrêté |
| C2 | `up` / `up-full` n'ont pas `--env-file .env`. Compose lit le `.env` du répertoire du fichier compose (`infra/compose/`), qui n'existe pas. Seul `up-iot` passe le bon fichier. | `Makefile:48,51` + cibles `capture-*` | **Bloquant probable** : `POSTGRES_PASSWORD`, `JWT_SECRET`, `REMEDIATION_TOKEN` vides, sauf si le shell les a exportés |
| C3 | Pas de `.dockerignore` à la racine, alors que 8 builds prennent la racine comme contexte (payment-api, auth, face-id, collector, detector, remediation, waf-exporter, assistant). | racine | Risque qu'un `COPY` large embarque `.env`/clés/caches. *Estimation initiale « ~330 Mo transférés » infirmée par la mesure : BuildKit ne transfère que les chemins des `COPY` (~50 kB) — gain de sécurité, pas de vitesse* |
| C4 | `up` dépend de `make model`, qui entraîne sur l'hôte avec `python3` (scikit-learn local requis), alors que le Dockerfile detector ré-entraîne déjà au build (étape `trainer`). | `Makefile:41-48`, `ml/detector/Dockerfile:25` | Entraînement fait deux fois, et échec sur un poste sans sklearn |
| C5 | `--build` est systématique et `PIP_NO_CACHE_DIR=1` sans cache BuildKit. | `Makefile`, tous les Dockerfiles Python | Tout changement de `requirements.txt` re-télécharge tout (sklearn, fastapi…), et chaque `up` repasse par tous les builds |
| C6 | `depends_on` en liste simple, sans `condition: service_healthy`. | compose (payment-api, auth, remediation, waf, detector) | Démarrage en désordre, redémarrages en boucle au lancement, bruit dans les premières fenêtres ML |
| C7 | Dashboard et Grafana ne sont publiés nulle part (ni `ports:`, ni route WAF). | compose, `security/waf/nginx.conf` | Comment le jury voit le temps 5 ? À trancher (voir lot 4) |
| C8 | `graphify-out/` n'est ni dans `.gitignore`, ni (une fois créé) dans `.dockerignore`. | racine | Bruit dans `git status` et dans le contexte de build |

---

## Lots

### Lot 0 — Mesure de référence (15 min)
- Chronométrer `make down && time make up-full` (premier build, puis rebuild à vide) et noter la taille de contexte
  affichée par BuildKit (`transferring context: …`).
- Sert de preuve « avant/après » pour la ROADMAP et le dossier.

### Lot 1 — Correctifs bloquants (C1, C2) · priorité P0
**Code :**
- `Makefile` : variable `COMPOSE := docker compose -f infra/compose/docker-compose.yml --env-file .env`.
  Toutes les cibles en héritent, y compris `capture-*`.
- `up` : `--profile demo --profile ml` ; `up-full` : `+ --profile full` ; `up-iot` : `+ --profile ml`.
- `down` : ajouter `--profile ml`.
- Garde-fou : `up*` échoue avec un message clair si `.env` est absent après `decrypt`.

**Tests** (`infra/tests/`) :
- test statique : chaque cible `up*` du Makefile active le profil `ml`, et `down` couvre tous les profils déclarés
  dans le compose (lus depuis le YAML, pas codés en dur) ;
- test statique : `COMPOSE` contient `--env-file .env`.

**Doc :** README racine (§ Installation), `docs/commandes.md` (retirer les ⚠️), `infra` README si concerné.

### Lot 2 — Build plus léger et plus rapide (C3, C5, C8) · P1
**Code :**
- `.dockerignore` racine : `.git`, `.venv`, `**/node_modules`, `**/__pycache__`, `**/.pytest_cache`,
  `.ruff_cache`, `graphify-out`, `docs/sujet`, `docs/dossier`, `.env`, `*.age`, `**/dist`, `infra/ansible/backups`.
  À vérifier : le detector a besoin de `ml/training/data/*.csv` et le remediation de ses playbooks. **Ne pas** exclure
  `ml/training/data`.
- Dockerfiles Python : `RUN --mount=type=cache,target=/root/.cache/pip pip install …` et retrait de `PIP_NO_CACHE_DIR`
  dans l'étape builder seulement. Image finale inchangée.
- `.gitignore` : `graphify-out/`.

**Tests :**
- test statique : le `.dockerignore` racine existe et exclut `.env`, `.git`, `.venv` (sécurité, sondée par le jury) ;
- `infra/tests/test_compose_hardening.py` : rien ne change côté durcissement, les tests existants doivent rester verts ;
- build manuel de chaque image, puis `make verify` OK.

**Doc :** `security/hardening/hardening.md` (le `.dockerignore` comme contrôle anti-fuite), ADR courte si l'équipe le souhaite.

### Lot 3 — Lancement rapide sans rebuild (C4, C5) · P1
**Code :**
- Retirer `model` des dépendances de `up` / `up-full`, puisque le build detector entraîne. Garder `make model` comme
  outil (le documenter « optionnel », ou le faire pointer sur `make train`, qui tourne dans Docker).
- Nouvelles cibles :
  - `make build` : `$(COMPOSE) --profile demo --profile ml --profile full build` ;
  - `make start` : `up -d` **sans** `--build` (relance quotidienne, quelques secondes) ;
  - `make up` garde `--build` (premier lancement / après pull).
- `make train-only` (alias lisible de `make train`) et `make retrain-detector` (`train` puis `build detector` puis
  `up -d detector`).

**Tests :** test statique des dépendances de cibles (`up` ne dépend plus de `model`).

**Doc :** `docs/commandes.md` §2 et §4, `ml/training/README.md` §6 (étape 6 → `make retrain-detector`).

### Lot 4 — Démarrage ordonné et visibilité démo (C6, C7) · P2
**Code :**
- `depends_on` avec `condition: service_healthy` : postgres → payment-api/auth/remediation ;
  payment-api/auth/front → waf ; remediation → detector/dashboard ; prometheus → collector.
- Ajouter les healthchecks manquants si besoin (collector, prometheus).
- C7, **décision équipe requise** : publier dashboard (et Grafana) en `127.0.0.1:<port>` uniquement (pas `0.0.0.0`,
  conforme à la règle « seul le WAF est exposé » côté réseau), **ou** les router via le WAF avec authentification.
  À valider avec l'agent `security-reviewer`.

**Tests :**
- test statique : chaque `depends_on` vers postgres utilise `service_healthy` ;
- toute publication de port non-WAF est liée à `127.0.0.1` (règle déjà sondée par `test_compose_hardening.py`, à étendre) ;
- e2e : `make up-full && make seed && make verify` sur un poste propre.

**Doc :** `docs/network.md`, `security/hardening/hardening.md`, README (§ Vérifier le système).

---

## Ordre et estimation

| Lot | Priorité | Effort | Dépend de |
|---|---|---|---|
| 0 Mesure | — | 15 min | — |
| 1 Profils + env | **P0** | 1 h | — |
| 2 `.dockerignore` + cache pip | P1 | 1 h 30 | — |
| 3 `start` / `build` / retrait `model` | P1 | 1 h | 1 |
| 4 Healthy + accès dashboard | P2 | 2 h + décision | 1 |

Les lots 1 et 2 touchent des fichiers disjoints (Makefile d'un côté, `.dockerignore`/Dockerfiles de l'autre) et peuvent
être menés en parallèle. Le lot 3 modifie le Makefile après le lot 1.

## Hors périmètre
- CI : reportée en fin de sprint (décision équipe, `CLAUDE.md`).
- Changer la logique de détection ou la table de décision.
