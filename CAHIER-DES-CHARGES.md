# Cahier des charges maître — PROJECT RESILIENCE-ALPHA

**Consortium G1 · Workshop National EPSI M2 2026-27 · Sprint du 19 au 23 octobre 2026**

> Démonstrateur de **cyber-résilience et de reprise autonome** (*Zero-Touch Recovery*). Une plateforme de paiement fictive conteneurisée subit une attaque lancée depuis un PC distinct ; une anomalie est détectée par ML, une décision de remédiation est prise et exécutée automatiquement, et le retour à la normale est prouvé par une transaction fictive réussie — **sans intervention corrective humaine**.

Ce document est le **contrat global** entre l'équipe et le sujet. Chaque exigence du sujet y est tracée vers le composant qui la réalise. Les cahiers des charges par projet (`*/CAHIER-DES-CHARGES.md`) détaillent chacun leur périmètre ; ce document maître garantit qu'**absolument rien n'est oublié**.

---

## 1. Objectif et critère de réussite unique

> **La démo en 5 temps, jouable d'une commande, filmable en ≤ 60 s sans coupure :**
> `avant` (verify_tx OK) → `attaque` (depuis le PC Attaquant) → `détection` (ML) → `remédiation` (automatique) → `après` (verify_tx OK), avec timeline + MTTD/MTTR affichés sur le dashboard.

Tout le reste sert ce critère. L'**Axe 1 du jury (5 pts)** et la **sanction ND/0** en cas d'intervention humaine en font le point le plus décisif du sujet.

---

## 2. Traçabilité exigence → composant

| # | Exigence du sujet | Composant(s) | CDC projet | Statut |
|---|---|---|---|---|
| **R1** | SI de paiement fictif : front, API métier, auth, BDD, microservices conteneurisés | `services/front`, `services/payment-api`, `services/auth`, Postgres | ✔ | voir ROADMAP |
| **R2** | Transaction fictive initiable et traçable | `services/payment-api`, `scripts/verify_tx` | ✔ | — |
| **R3** | Moteur de remédiation : reçoit l'incident, agit, suit le retour à l'état utilisable | `remediation/` | ✔ | — |
| **R4** | Interface de supervision (composants, événements, alertes, avancement reprise) | `dashboard/` | ✔ | — |
| **R5** | Déploiement reproductible Docker Compose | `infra/compose/` | ✔ | — |
| **R6** | Playbooks Ansible pour les opérations et la reprise | `infra/ansible/` | ✔ | — |
| **R7** | Observabilité : Prometheus (métriques), Grafana (visu), Loki (logs) | `infra/prometheus\|grafana\|loki\|promtail` | ✔ | — |
| **R8** | Détection d'anomalies par **ML** (pas de conditions codées en dur), raccordée à la remédiation | `ml/collector`, `ml/training`, `ml/detector` | ✔ | — |
| **R9** | Assistant local **RAG** (Ollama + LangChain, modèle ≤ 8B), séparé de l'automate | `assistant/` | ✔ | — |
| **R10** | Au moins un scénario d'attaque **depuis un PC distinct**, effet observable | `attacks/` + PC Attaquant | ✔ | — |
| **R11** | WAF (filtrage applicatif), seul point exposé | `security/waf/` (Nginx + ModSecurity + CRS) | ✔ | — |
| **R12** | SIEM **ou** fonction SOC intégrée à la supervision | `infra/loki` + règles Grafana/Loki ruler | ✔ | — |
| **R13** | Gestion des secrets : Vault **ou** SOPS | `security/sops/` (SOPS + age) | ✔ | — |
| **R14** | Durcissement des composants et des accès, privilèges maîtrisés | `security/hardening/` + Compose | ✔ | — |
| **R15** | Moteur de remédiation à privilèges maîtrisés (pas d'admin ouverte) | `remediation/` (docker-socket-proxy, API authentifiée) | ✔ | — |
| **R16** | Analyse de risques **EBIOS RM** reliée à l'architecture | `docs/ebios-rm.md` | ✔ | **J1** |
| **R17** | Objectifs de continuité + **PCA/PRA** (RTO/RPO, scénarios, risques résiduels) | `docs/pca-pra.md` | ✔ | — |
| **R18** | Analyse **NIS2 / DORA** reliée au démonstrateur | `docs/nis2-dora.md` | ✔ | — |
| **R19** | Réseau : WAF seul exposé, DB/secrets/management internes, hôte `192.168.137.1` sur `RESILIENCE-G1` | `infra/compose` (3 réseaux) + `docs/network.md` | ✔ | — |
| **R20** | Démo visible **avant / pendant / après** l'incident | `dashboard/` + `scripts/demo.sh` | ✔ | — |

### Livrables impératifs (§7 du sujet — nommage strict)

| Livrable | Fichier | Contrainte |
|---|---|---|
| Dossier d'ingénierie et gouvernance | `Workshop2026-M2-G1-Dossier.pdf` | 8–12 pages hors annexes |
| Support de présentation | `Workshop2026-M2-G1-Pres.pptx` | pitch court |
| Clip Chrono | `Workshop2026-M2-G1-VidChrono.mp4` | **≤ 60 s, séquence continue sans coupe** |
| Archive sources + déploiement | `Workshop2026-M2-G1-Code.zip` | README de déploiement, **aucun secret en clair** |

> Génération : `scripts/package_deliverables.sh` assemble le zip depuis le dépôt (hors `.git`, hors clés). Le dossier et les slides sont rédigés dans `docs/dossier/` puis exportés.

---

## 3. Décisions d'architecture (corrections intégrées depuis la review)

| Décision | Choix retenu | Justification |
|---|---|---|
| Langage backend | Python 3.12 + FastAPI partout | Mono-langage, synergie scikit-learn, OpenAPI gratuit |
| Base de données | PostgreSQL 16, réseau `data` interne | Transactionnel, dumps pour PRA |
| Front & dashboard | React + Vite + Tailwind (2 apps) | Imposé par le sujet (React/Tailwind) |
| WAF | Nginx + ModSecurity + OWASP CRS | Seul point exposé (80/443) |
| Observabilité | Prometheus + Loki + Promtail + Grafana + Alertmanager + cAdvisor | Elastic explicitement **écarté** par le sujet (RAM) |
| SIEM/SOC | **Fonction SOC** = règles Loki/Grafana ruler (Wazuh en profil optionnel) | 16 Go RAM ; le sujet autorise « une fonction SOC intégrée » |
| Secrets | SOPS + age, fichiers `*.enc.*` commités chiffrés | Clé age **hors git** ; clé de démo fournie hors archive |
| Remédiation | FastAPI + **docker-socket-proxy** (verbes limités) + `ansible-runner` | Privilèges maîtrisés (correction review : jamais le socket brut) |
| IA / RAG | Ollama (`qwen2.5:7b` ou `llama3.1:8b`) + LangChain + Chroma | ≤ 8B ; **déporté sur le PC IA** si RAM serrée |
| Attaque | **PC Attaquant physique** sur le hotspot (profil Compose `attack` = fallback dev uniquement) | Correction review : le sujet impose un PC distinct |

### Trois corrections majeures issues de la review (actées)

1. **Attaque depuis un vrai 2e PC** pour la démo notée et le Clip Chrono — le profil Compose `attack` ne sert qu'au dev.
2. **Assistant RAG dans le périmètre livrable** (pas optionnel) — pilier IA/DATA obligatoire.
3. **EBIOS RM démarré en J1** (livrable du lundi), relié à l'architecture réelle — pas de rapport générique.

Et le durcissement du **moteur de remédiation** (point explicitement sondé par le jury) : docker-socket-proxy, API authentifiée, hors réseau `edge`, moindre privilège documenté.

---

## 4. Topologie réseau (R19)

```
┌───────────────── PC Hôte (192.168.137.1, hotspot RESILIENCE-G1) ─────────────────┐
│  réseau edge   : WAF (80/443 exposés)  ─┐                                          │
│  réseau app    : front, payment-api, auth, detector, collector, remediation       │
│  réseau data   : postgres, pg-exporter        (internal: true — jamais exposé)    │
│  réseau obs    : prometheus, loki, promtail, grafana, alertmanager, cadvisor      │
│                                                                                    │
│  Seul le WAF est joignable depuis le hotspot. DB, secrets, API remediation,        │
│  interfaces de gestion : internes uniquement (jamais 0.0.0.0).                     │
└────────────────────────────────────────────────────────────────────────────────────┘
        ▲
        │ attaque (HTTPS vers le WAF uniquement)
┌───────┴────────┐        ┌────────────────────────┐
│ PC Attaquant   │        │ PC IA (optionnel)      │
│ outils Red Team│        │ Ollama exposé en API   │
└────────────────┘        └────────────────────────┘
```

Détail et pare-feu Windows : `docs/network.md`. Périmètre offensif strictement limité au SI du projet ; kill-switch dans `attacks/README.md`.

---

## 5. Definition of Done (le flow imposé)

> **Aucune tâche n'est « terminée » tant que les quatre points ne sont pas faits :**
>
> 1. **Code** — fonctionnel, conforme aux [contrats d'interfaces](docs/contracts.md).
> 2. **Tests** — unitaires (et e2e si applicable) écrits et **verts**.
> 3. **Doc** — README/CDC du projet et doc transverse à jour.
> 4. **Avancement** — ligne mise à jour dans [`ROADMAP.md`](ROADMAP.md).
>
> Ce cycle est détaillé dans [`CLAUDE.md`](CLAUDE.md) et outillé par la commande `/avancer`.

---

## 6. Correspondance avec la grille d'évaluation

| Axe jury (local, /20 ×2) | Points | Ce qui le couvre ici |
|---|---|---|
| Axe 1 — Démo live + remédiation autonome | 5 | §1, R2/R3/R10/R20, `scripts/demo.sh`, boucle `verify_tx` |
| Axe 2 — Expertise technique, 5 domaines interconnectés, accès remédiation maîtrisé | 4 | Les 5 piliers (R1–R18), R15 |
| Axe 3 — Clip Chrono + dashboard | 4 | R4, R20, Clip ≤ 60 s |
| Axe 4 — Gouvernance NIS2/DORA + pitch | 4 | R16/R17/R18, `docs/dossier/` |
| Axe 5 — Dossier + réponses + contribution de chacun | 3 | `docs/dossier/`, ROADMAP (contributions) |

Suivi individuel (/20 ×1) : leadership, expertise, résolution de problèmes, coopération, rigueur/traçabilité — soutenu par la discipline de commits + ROADMAP.

---

## 7. Chronologie du sprint (reliée à la roadmap)

| Jour | Attendu sujet | Jalons G1 |
|---|---|---|
| **Lun J1** | Kick-off, architecture, **EBIOS**, interfaces | Phase 0 + contrats figés + EBIOS v1 |
| **Mar J2** | Déploiement Compose/Ansible, microservices, ML, Red Team, gouvernance | Phases 1–3 |
| **Mer J3** | Interconnexion WAF/SIEM, détection, remédiation, dashboard, 1ers tests | Phases 2–5 |
| **Jeu J4** | Recette, chaos engineering, **Clip Chrono, gel du code à 17h** | Phase 6–8, packaging |
| **Ven J5** | Jury local (pas de production) | Démo |

Détail jour par jour, propriétaires et avancement : [`ROADMAP.md`](ROADMAP.md).
