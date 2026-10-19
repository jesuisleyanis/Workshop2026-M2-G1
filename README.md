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

*Schéma détaillé et description des flux : voir [`docs/architecture.md`](docs/architecture.md) (à venir).*

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

# Procédure détaillée à compléter au fil du sprint
```

## Vérifier le système

*À compléter : URLs des services, comptes de test fictifs, commande de transaction de vérification.*

## Scénario de démonstration

1. **Avant** — le service est nominal, une transaction fictive est exécutée avec succès.
2. **Attaque** — lancement du scénario depuis le PC Attaquant.
3. **Détection** — les métriques et journaux sont collectés, le modèle ML identifie l'anomalie.
4. **Remédiation** — le moteur de remédiation décide et exécute l'action corrective.
5. **Après** — le dashboard montre le retour à l'état nominal, une nouvelle transaction réussit.

## Structure du dépôt

*Structure prévisionnelle, à ajuster :*

```
.
├── services/          # Microservices (front, API, auth, …)
├── remediation/       # Moteur de remédiation
├── dashboard/         # Supervision React + Tailwind
├── ml/                # Détection d'anomalies
├── assistant/         # Assistant RAG (Ollama + LangChain)
├── infra/             # Docker Compose, Ansible, Prometheus, Grafana, Loki
├── security/          # WAF, SIEM, durcissement, secrets
├── attacks/           # Scripts Red Team
├── docs/              # Architecture, EBIOS RM, PCA/PRA, NIS2/DORA, procédures
└── tests/
```

## Gestion des secrets

Aucun secret ne doit être commité en clair. Les secrets sont gérés via HashiCorp Vault ou SOPS ; les fichiers `.env` locaux sont ignorés par Git.

## Livrables

Dossier de rendu : `Workshop2026-M2-G1`

| Fichier | Contenu |
|---|---|
| `Workshop2026-M2-G1-Dossier.pdf` | Dossier d'ingénierie et de gouvernance (8 à 12 pages hors annexes) |
| `Workshop2026-M2-G1-Pres.pptx` | Support de présentation |
| `Workshop2026-M2-G1-VidChrono.mp4` | Clip Chrono — 60 s max, sans coupe |
| `Workshop2026-M2-G1-Code.zip` | Archive du dépôt Git (sources, IaC, scripts, tests, doc, README) |

## Équipe

| Membre | Formation | Domaine(s) |
|---|---|---|
| Yanis | | |
| | | |
| | | |
| | | |
| | | |
