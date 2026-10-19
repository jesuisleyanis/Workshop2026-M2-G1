# Roadmap & suivi d'avancement — PROJECT RESILIENCE-ALPHA

> Tableau de bord unique de l'équipe G1. **Mettre à jour à chaque fin de tâche** (c'est l'étape 4 de la [Definition of Done](CAHIER-DES-CHARGES.md#5-definition-of-done-le-flow-imposé)).
> Légende statut : ⬜ à faire · 🟨 en cours · ✅ fait · 🔴 bloqué · ⏭️ reporté.

## Équipe & domaines (5 piliers)

| Pilier | Domaine | Référent | Composants |
|---|---|---|---|
| Développement | Métier + reprise | _à renseigner_ | `services/*`, `dashboard/`, `scripts/verify_tx` |
| Infrastructure | Déploiement, observabilité | _à renseigner_ | `infra/*`, exécution remédiation |
| IA / Data | Détection ML + RAG | _à renseigner_ | `ml/*`, `assistant/` |
| Cybersécurité | Red Team, WAF, SOC, secrets | _à renseigner_ | `security/*`, `attacks/` |
| Transformation | Gouvernance, risques, conformité | _à renseigner_ | `docs/ebios-rm.md`, `docs/pca-pra.md`, `docs/nis2-dora.md` |

> Une personne peut couvrir plusieurs domaines ; un domaine peut mobiliser plusieurs personnes (cf. sujet §3). Ce qui compte : une **contribution identifiable** par membre (traçable dans les commits et ici).

---

## Avancement global

```
Phase 0  Socle            [#########.]  90%   squelette, contrats, .claude, compose, SOPS
Phase 1  Plateforme       [########..]  85%   auth+payment+front livrés et testés
Phase 2  Infra & observ.  [########..]  85%   configs Prom/Loki/Grafana/Alert/Ansible OK
Phase 3  Détection ML     [#########.]  90%   outillage données réelles OK (75 tests) ; capture réelle à jouer
Phase 4  Remédiation      [######....]  60%   code + CDC + README ; câblage à réconcilier
Phase 5  Dashboard        [########..]  85%   dashboard + front livrés (src+tests)
Phase 6  Cyber & attaques [########..]  85%   WAF, SOPS, durcissement, 4 scénarios OK
Phase 7  Assistant RAG    [#########.]  90%   RAG livré (97 tests)
Phase 8  Gouvernance      [########..]  80%   EBIOS/PCA/NIS2 rédigés, reliés à l'archi
```

> Scaffold initial généré en J1 (structure pro, tests par composant, docs). Les services backend, le moteur de remédiation, le dashboard et les docs de gouvernance sont en cours de finalisation. Validation live (`make up`) et ré-entraînement ML sur vraies séries Prometheus restent à faire.

---

## J1 — Lundi : socle, architecture, EBIOS, contrats

| Tâche | Composant | Réf. | Propriétaire | Statut | Preuve (commit/test) |
|---|---|---|---|---|---|
| Arborescence monorepo + README racine | — | — | — | ✅ | arborescence + README |
| Contrats d'interfaces figés | `docs/contracts.md` | R8 | — | ✅ | `docs/contracts.md` |
| Cahier des charges maître | `CAHIER-DES-CHARGES.md` | tous | — | ✅ | — |
| Librairie partagée (logs/métriques/événement) | `libs/python/resilience_common` | R8 | — | ✅ | 4 tests verts |
| `.claude/` (settings, agents, skills, commandes) | `.claude/` | — | — | ✅ | settings + 3 agents + skill + 2 cmds |
| Compose : 4 réseaux + profils + socket-proxy | `infra/compose` | R5,R19,R15 | — | ✅ | `docker-compose.yml` |
| SOPS + age + `.sops.yaml` + `.gitignore` | `security/sops` | R13 | — | ✅ | README + decrypt-secrets.sh |
| gitleaks + ruff pre-commit | `.pre-commit-config.yaml` | R13 | — | ✅ | config présente (`pre-commit install` au poste) |
| **EBIOS RM v1** (valeurs métier, sources de risque, scénarios) | `docs/ebios-rm.md` | R16 | — | ✅ | docs/ebios-rm.md |
| `docs/architecture.md` + `docs/network.md` + ADR | `docs/` | R19 | — | ✅ | architecture.md, network.md, 3 ADR |

## J2 — Mardi : plateforme, infra, ML

| Tâche | Composant | Réf. | Propriétaire | Statut | Preuve |
|---|---|---|---|---|---|
| auth : login/register, JWT, bcrypt, rate-limit | `services/auth` | R1 | — | ✅ | 35 tests verts (métriques contrat §2) |
| payment-api : comptes, transactions, health/ready, métriques | `services/payment-api` | R1,R2 | — | ✅ | 54 tests verts (+1 skip Postgres) |
| front : login, solde, virement, historique | `services/front` | R1 | — | ✅ | CDC+README+src+tests |
| seed + verify_tx | `scripts/` | R2 | — | ✅ | scripts/verify_tx, scripts/seed.py |
| Observabilité provisionnée (Prom/Loki/Grafana/Alert) | `infra/*` | R7 | — | ✅ | configs + provisioning |
| WAF Nginx+ModSec+CRS devant le front | `security/waf` | R11 | — | ✅ | nginx.conf + waf_exporter (5 tests) |
| Durcissement conteneurs (non-root, cap_drop, read_only) | `security/hardening` | R14 | — | ✅ | hardening.md + audit.sh (OK) |
| collector (features) + training (IsolationForest) | `ml/collector`, `ml/training` | R8 | — | ✅ | 50 tests ML verts |
| EBIOS v2 + début NIS2/DORA | `docs/` | R16,R18 | — | ✅ | ebios-rm.md, nis2-dora.md |

## J3 — Mercredi : détection, remédiation, dashboard, interconnexion

| Tâche | Composant | Réf. | Propriétaire | Statut | Preuve |
|---|---|---|---|---|---|
| detector : score temps réel + émission événement | `ml/detector` | R8 | — | ✅ | detector tests (AnomalyEvent validé) |
| Moteur de remédiation + table de décision | `remediation/` | R3,R15 | — | 🟨 | code + CDC + README présents (~40 tests, non relancés) ; câblage à réconcilier |
| docker-socket-proxy + API authentifiée | `remediation/`, `infra/compose` | R15 | — | ✅ | haproxy strict câblé + Bearer statique (ADR 0002) |
| Playbooks Ansible (deploy + remédiation) | `infra/ansible` | R6 | — | ✅ | deploy, block_ip, restore_pg_dump |
| Alertmanager → webhook remédiation | `infra/alertmanager` | R7 | — | ✅ | alertmanager.yml |
| Règles SOC Loki/Grafana | `infra/grafana`, `infra/loki` | R12 | — | ✅ | soc-rules.yml |
| Dashboard (états, score, timeline, MTTD/MTTR, SSE) | `dashboard/` | R4,R20 | — | ✅ | CDC+README+src+tests |
| Scénarios d'attaque v1 (depuis PC Attaquant) | `attacks/` | R10 | — | ✅ | 4 scénarios (4 tests contrat) |
| RAG : indexation docs + journal, UI onglet | `assistant/` | R9 | — | ✅ | 97 tests verts |

## J4 — Jeudi : recette, chaos, clip, gel du code (17h)

| Tâche | Composant | Réf. | Propriétaire | Statut | Preuve |
|---|---|---|---|---|---|
| Tests e2e rejouant chaque scénario | `tests/e2e` | R10 | — | 🟨 | squelette prêt (skip si stack down) |
| Chaos engineering (pannes non-attaque) | `attacks/`, `tests/e2e` | — | — | ⬜ | — |
| ML sur vraies séries Prometheus : outillage (capture, train `--data`, calibration seuil + MTTD, trafic légitime, train au build) | `ml/*`, `scripts/gen_normal_traffic.py` | R8 | — | ✅ | ml 75 tests + scripts 7 tests verts ; `ml/training/README.md` §6 |
| ML sur vraies séries : capture baseline + 4 scénarios, calibration, rebuild detector | `ml/training/data/` | R8 | — | ⬜ | à jouer stack levée (`make capture-baseline` … §6) |
| `scripts/demo.sh` (5 temps enchaînés) | `scripts/` | R20 | — | ✅ | scripts/demo.sh |
| PCA/PRA (RTO/RPO, risques résiduels) | `docs/pca-pra.md` | R17 | — | ✅ | docs/pca-pra.md |
| NIS2/DORA finalisé | `docs/nis2-dora.md` | R18 | — | ✅ | docs/nis2-dora.md |
| Dossier PDF 8–12 p + slides | `docs/dossier/` | §7 | — | ⬜ | — |
| **Clip Chrono ≤ 60 s** | `Workshop2026-M2-G1-VidChrono.mp4` | §7 | — | ⬜ | — |
| `Code.zip` (sans secrets) | `scripts/package_deliverables.sh` | §7 | — | ✅ | package_deliverables.sh (audit intégré) |
| **Gel du code 17h** | — | — | — | ⬜ | — |

---

## Journal de décisions (ADR)

Décisions d'architecture structurantes : voir `docs/adr/`. Résumé rapide :

| Date | Décision | Statut |
|---|---|---|
| J1 | Mono-langage Python/FastAPI | acté |
| J1 | SOC = règles Loki/Grafana (pas Wazuh par défaut) | acté |
| J1 | Remédiation via docker-socket-proxy, jamais le socket brut | acté |
| J1 | Attaque depuis PC physique pour la démo (profil `attack` = dev) | acté |

## Points d'intégration (câblage)

| # | Écart | Résolution | Preuve |
|---|---|---|---|
| I1 | Proxy Docker | **haproxy** retenu (liste blanche stricte 4 chemins) ; tecnativa retiré ; câblé dans compose | ADR 0002 maj, `docker-compose.yml` |
| I2 | Variable verify_tx | compose aligné sur `VERIFY_TX_PATH` | `docker-compose.yml` |
| I3 | Noms de playbooks | `block_ip.yml`→`waf_deny_ip.yml`, `restore_pg_dump.yml`→`pg_restore.yml` | `infra/ansible/playbooks/` |
| I4 | Auth moteur | **Bearer statique interne** acté (service non exposé) | `contracts.md §API`, ADR 0002 |
| I6 | Detector -> remédiation | compose : `REMEDIATION_URL` sans `/events` (chaque événement en 404) -> URL complète | `ml/detector/tests/test_compose_wiring.py` |
| I7 | Build image detector | le Dockerfile copiait des artefacts non versionnés (build impossible) -> modèle entraîné au build | `ml/detector/Dockerfile` (étape `trainer`) |
| I8 | 🔴 `verify_tx` vs payment-api | `verify_tx` envoie `dst_account` = IBAN (chaîne) sans `src_account` ; l'API attend des **ids entiers** (`StrictInt`) -> 422 : la vérification de reprise échoue toujours (même défaut dans `attacks/run.sh` service_flood). `seed.py` envoie `iban_fake`/`balance_cents`, ignorés par `register` (IBAN aléatoire, solde par défaut) | **à corriger** |
| I5 | Métriques HTTP lib | `instrument()` réécrit (middleware) → `resilience_http_requests_total{service,method,path,status}` ; `xfail` retirés ; conftests nettoyés | auth 35/35, payment-api 54/54 |

## Risques projet (vivant)

| Risque | Impact | Parade | Statut |
|---|---|---|---|
| RAM 16 Go saturée par Ollama + stack | démo qui rame | Ollama sur PC IA ; profil Compose « démo » minimal | surveillé |
| ML instable sur 60 s | démo ratée (Axe 1) | dataset baseline solide + seuil de secours documenté comme limite | surveillé |
| Attaque pas prête sur 2e PC | perte Axe 1 | profil `attack` en secours, mais viser le 2e PC tôt | surveillé |
| Déploiement non reproductible | pénalité §3.2 | Ansible + README testés sur machine vierge | surveillé |
