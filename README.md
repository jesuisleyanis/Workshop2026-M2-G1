# Workshop2026-M2-G1 — PROJECT RESILIENCE-ALPHA

> « Tout système finit par tomber. La vraie question : le vôtre saura-t-il se relever seul ? »

Démonstrateur de **cyber-résilience et de reprise autonome** (*Zero-Touch Recovery*) réalisé dans le cadre du Workshop national EPSI M2 2026-27 par le consortium **G1**.

Une plateforme de paiement **fictive** et conteneurisée subit une attaque lancée depuis un PC Attaquant distinct. L'anomalie est détectée par un modèle de machine learning, une décision de remédiation est prise puis exécutée automatiquement, et le service est vérifié par une nouvelle transaction réussie — sans intervention corrective humaine.

> ⚠️ Toutes les données (comptes, transactions, utilisateurs) sont fictives. Aucune donnée bancaire réelle n'est utilisée. Les actions offensives sont strictement limitées au SI de l'équipe.

---

## Sommaire

- [Architecture](#architecture)
- [Les cinq piliers](#les-cinq-piliers)
- [Environnement matériel et réseau](#environnement-matériel-et-réseau)
- [Prérequis](#prérequis)
- [Installation et déploiement](#installation-et-déploiement)
- [Vérifier le système](#vérifier-le-système)
- [Tests](#tests)
- [Scénario de démonstration](#scénario-de-démonstration)
- [Structure du dépôt](#structure-du-dépôt)
- [Gestion des secrets](#gestion-des-secrets)
- [Livrables](#livrables)
- [Équipe](#équipe)

---

## Architecture

```
                 ┌──────────────── PC Hôte (192.168.137.1) ────────────────┐
 PC Attaquant ──►│  WAF ──► Front web (React) ──► API paiement ──► Base de données │
                 │              │                     │                         │
                 │              └──► Service d'authentification                 │
                 │                                                              │
                 │  Prometheus · Loki · Grafana ──► Détection ML (AIOps)        │
                 │  SIEM / SOC                         │                        │
                 │                                     ▼                        │
                 │                     Moteur de remédiation (+ Ansible)        │
                 │                                     │                        │
                 │                     Dashboard de supervision (React/Tailwind)│
                 │                                                              │
                 │  Vault / SOPS (secrets)                                      │
                 └──────────────────────────────────────────────────────────────┘
                          PC IA (facultatif) : Ollama + assistant RAG
```

*Schéma détaillé et description des flux : voir [`docs/architecture.md`](docs/architecture.md).*

## Les cinq piliers

| Domaine | Contenu | Technologies |
|---|---|---|
| **Développement** | SI de paiement en microservices (front, API métier, authentification, BDD), moteur de remédiation, dashboard de supervision | Node.js / Python FastAPI / Go, REST ou gRPC, React + Tailwind CSS |
| **Infrastructure** | Déploiement reproductible, automatisation des opérations, observabilité | Docker Compose, Ansible, Prometheus, Grafana, Loki |
| **IA / Data** | Détection d'anomalies par ML sur métriques/journaux, assistant opérateur local RAG (≤ 8 Md paramètres) | scikit-learn (ou équivalent), Ollama, LangChain |
| **Cybersécurité** | Scénario(s) d'attaque Red Team, WAF, SIEM/SOC, durcissement, gestion des secrets | WAF, SIEM, HashiCorp Vault ou SOPS |
| **Transformation** | Analyse de risques, objectifs de continuité, PCA/PRA, conformité | EBIOS RM, NIS2, DORA |

## Environnement matériel et réseau

| Poste | Rôle |
|---|---|
| **PC Hôte** | Exécute l'ensemble des services — Windows 10/11, Docker Desktop + WSL2, ≥ 4 cœurs, ≥ 16 Go RAM, ≥ 50 Go SSD |
| **PC Attaquant** | Lance les scénarios offensifs (≥ 8 Go RAM) |
| **PC IA** *(facultatif)* | Héberge uniquement le modèle de langage et son interface |

Réseau : point d'accès sans fil mobile Windows **`RESILIENCE-G1`**, PC Hôte en **`192.168.137.1`**.
Seuls les services nécessaires sont exposés ; base de données, secrets et interfaces de gestion restent internes.

## Prérequis

- Docker Desktop (WSL2 activé) et Docker Compose v2
- Ansible
- Git
- Ollama (sur le PC Hôte ou le PC IA)

## Installation et déploiement

```bash
git clone https://github.com/jesuisleyanis/Workshop2026-M2-G1.git
cd Workshop2026-M2-G1

# 1. Secrets : chiffrer security/sops/secrets.example.env -> secrets.enc.env (voir security/sops/README.md)
# 2. Lever la stack (profil démo minimal) puis peupler les données fictives
make up          # ou `make up-full` pour l'observabilité complète
make up-iot      # sur le PC Hôte avec le PA actif : ajoute Mosquitto (profil iot)
make seed        # comptes fictifs demo01..demo05 financés

# Détails des cibles make : `make help` ; procédures scripts : scripts/README.md
```

Toutes les commandes (lancer, entraîner le ML seul, démontrer, tester, dépanner) : [`docs/commandes.md`](docs/commandes.md).
Plan d'optimisation du lancement : [`docs/plan-optimisation-lancement.md`](docs/plan-optimisation-lancement.md).

## Vérifier le système

- **WAF (seul point HTTP exposé)** : `https://localhost` (80/443) — front « Banque Résilience » ; les API internes ne sont pas publiées. Le profil `iot` expose uniquement MQTT sur `192.168.137.1:1883`.
- **Back-office (PC Hôte uniquement)** : `https://localhost:9443` — listener WAF lié à `127.0.0.1` (authentification visage + mot de passe, administration des agents ; ADR 0007). Pas à pas (lancement, premier admin, login facial, LED ESP8266, dépannage) : [`docs/RUNBOOK-BACKOFFICE-FACIAL.md`](docs/RUNBOOK-BACKOFFICE-FACIAL.md).
- **Comptes de test fictifs** : `demo01` … `demo05`, mot de passe commun `SEED_PASSWORD` (SOPS, cf. `security/sops/secrets.example.env`).
- **Transaction de contrôle** : `make verify` (code retour `0` = transaction fictive rejouée OK). Démo complète : `make demo` (5 temps). Détails : [`scripts/README.md`](scripts/README.md).

## Tests

`make test` lance **un process pytest par composant** (`libs`, `services/*`, `ml`, `remediation`,
`assistant`) puis les répertoires de tests de contrat (`security/waf/tests`, `attacks/tests`,
`scripts/tests`, `infra/tests`, `tests/e2e`), et enfin Vitest (`services/front`, `services/backoffice`,
`dashboard`). `services/face-id` fait partie des composants Python (backend `stub` : ni dlib ni modèle requis).
Un seul process pour tout le dépôt n'est pas possible : chaque service déclare ses métriques
Prometheus à l'import (`DuplicateTimeseries`).

Les tests Python exigent un interpréteur **3.12** où les dépendances de *tous* les composants sont
installées, y compris les libs partagées `resilience_common` / `resilience_db` :

```bash
uv venv --python 3.12 .venv && source .venv/bin/activate     # ou python3.12 -m venv .venv
uv pip install -e "libs/python/resilience_common[fastapi,test]" -e "libs/python/resilience_db[test]" \
  -e services/auth -e services/payment-api -e services/face-id \
  -r remediation/requirements-dev.txt -r assistant/requirements-dev.txt
( cd ml && uv pip install -r requirements-dev.txt )   # chemin relatif ../libs dans le fichier
make test                                             # ou : make test-py PYTHON=.venv/bin/python
```

Les tests front exigent leurs dépendances (`npm ci` dans `services/front`, `services/backoffice` et `dashboard`) :
sans elles, `make test` échoue (c'est voulu : l'agrégat reflète l'état réel). Le back-office exige **Node ≥ 22.15
(ou 24)** : la version d'undici embarquée par jsdom ne se charge pas sur Node 20. `make test-py` ne lance que la
partie Python, `make test-front` que Vitest.

Chaque composant reste testable seul depuis son répertoire (`cd remediation && pytest`), voir son `README.md`.

## Scénario de démonstration

1. **Avant** — le service est nominal, une transaction fictive est exécutée avec succès.
2. **Attaque** — lancement du scénario depuis le PC Attaquant.
3. **Détection** — les métriques et journaux sont collectés, le modèle ML identifie l'anomalie.
4. **Remédiation** — le moteur de remédiation décide et exécute l'action corrective.
5. **Après** — le dashboard montre le retour à l'état nominal, une nouvelle transaction réussit.

## Documents de référence

| Document | Rôle |
|---|---|
| [`CAHIER-DES-CHARGES.md`](CAHIER-DES-CHARGES.md) | Cahier des charges maître — traçabilité exigence → composant |
| [`docs/contracts.md`](docs/contracts.md) | **Contrats d'interfaces** (logs, métriques, événement d'anomalie, table de décision) — figés |
| [`docs/architecture.md`](docs/architecture.md) | Architecture technique et flux de la reprise autonome |
| [`docs/network.md`](docs/network.md) | Réseau, exposition, pare-feu |
| [`ROADMAP.md`](ROADMAP.md) | Roadmap et suivi d'avancement de l'équipe |
| [`CLAUDE.md`](CLAUDE.md) | Guide de contribution et flow de travail |
| [`docs/adr/`](docs/adr/) | Décisions d'architecture (ADR) |
| `docs/ebios-rm.md` · `docs/pca-pra.md` · `docs/nis2-dora.md` | Gouvernance et conformité |

## Structure du dépôt

```
.
├── services/          # Microservices métier (front, payment-api, auth)
├── remediation/       # Moteur de remédiation (décision + actions + vérification)
├── dashboard/         # Supervision React + Tailwind (timeline, MTTD/MTTR)
├── ml/                # Détection d'anomalies (collector, training, detector)
├── assistant/         # Assistant RAG (Ollama + LangChain + Chroma)
├── infra/             # Docker Compose, Ansible, Prometheus, Grafana, Loki, Promtail, Alertmanager
├── security/          # WAF (Nginx+ModSecurity+CRS), secrets (SOPS), durcissement
├── attacks/           # Banc d'essai Red Team (scénarios, kill-switch)
├── libs/python/       # Librairie partagée resilience_common (logs, métriques, schémas)
├── scripts/           # demo.sh, verify_tx, seed.py, decrypt-secrets.sh, package_deliverables.sh
├── docs/              # contracts, architecture, EBIOS RM, PCA/PRA, NIS2/DORA, ADR
└── tests/e2e/         # Rejeu des scénarios de bout en bout
```

Démarrage rapide : `make help` liste les commandes (`make up`, `make seed`, `make verify`, `make demo`, `make test`).

## Gestion des secrets

Aucun secret ne doit être commité en clair. Les secrets sont gérés via HashiCorp Vault ou SOPS ; les fichiers `.env` locaux sont ignorés par Git.

## Livrables

Dossier de rendu : `Workshop2026-M2-G1`

| Fichier | Contenu |
|---|---|
| `Workshop2026-M2-G1-Dossier.pdf` | Dossier d'ingénierie et de gouvernance (8 à 12 pages hors annexes) |
| `Workshop2026-M2-G1-Pres.pptx` | Support de présentation |
| `Workshop2026-M2-G1-VidChrono.mp4` | Clip Chrono — 60 s max, sans coupe (kit de production : `docs/dossier/clip/`) |
| `Workshop2026-M2-G1-Code.zip` | Archive du dépôt Git (sources, IaC, scripts, tests, doc, README) |

Clip Chrono : storyboard + script d'assemblage + validation dans `docs/dossier/clip/` ; le `.mp4` s'enregistre
en recette (voir son `README.md`). Procédure de **gel du code** J4 : [`docs/FREEZE-J4.md`](docs/FREEZE-J4.md).

Génération de l'archive : `make package` (ou `scripts/package_deliverables.sh`). Le script lance d'abord
`security/hardening/audit.sh`, exclut `.git`, dépendances (`node_modules`, venv), artefacts de build
(`dist`, caches, `*.egg-info`), journaux locaux, dumps et **tout secret déchiffré** (`.env`, `keys.txt`,
`*.age`), puis re-scanne l'archive (noms **et** contenu : clé age / clé privée) et l'efface en cas de doute.
La clé age de démo est remise **hors archive**. Les fichiers `Workshop2026-M2-G1-*` sont ignorés par git.

## Équipe

| Membre | Formation | Domaine(s) |
|---|---|---|
| Yanis | | |
| | | |
| | | |
| | | |
| | | |
