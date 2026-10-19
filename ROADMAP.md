# Roadmap & suivi d'avancement — PROJECT RESILIENCE-ALPHA

> Tableau de bord unique de l'équipe G1. **Mettre à jour à chaque fin de tâche** (c'est l'étape 4 de la [Definition of Done](CAHIER-DES-CHARGES.md#5-definition-of-done-le-flow-imposé)).
> Légende statut : ⬜ à faire · 🟨 en cours · ✅ fait · 🔴 bloqué · ⏭️ reporté.

## Équipe & domaines (5 piliers)

| Pilier | Domaine | Référent | Composants |
|---|---|---|---|
| Développement | Métier + reprise | _à renseigner_ | `services/*`, `dashboard/`, `scripts/verify_tx` |
| Infrastructure | Déploiement, observabilité | _à renseigner_ | `infra/*`, exécution remédiation |
| IA / Data | Détection ML + RAG | _à renseigner_ | `ml/*`, `assistant/` |
| Cybersécurité | Red Team, WAF, SOC, secrets | Louis | `security/*`, `attacks/` |
| Transformation | Gouvernance, risques, conformité | _à renseigner_ | `docs/ebios-rm.md`, `docs/pca-pra.md`, `docs/nis2-dora.md` |

> Une personne peut couvrir plusieurs domaines ; un domaine peut mobiliser plusieurs personnes (cf. sujet §3). Ce qui compte : une **contribution identifiable** par membre (traçable dans les commits et ici).

---

## Avancement global

```
Phase 0  Socle            [#########.]  90%   squelette, contrats, .claude, compose, SOPS
Phase 1  Plateforme       [########..]  85%   auth+payment+front livrés et testés
Phase 2  Infra & observ.  [########..]  85%   configs Prom/Loki/Grafana/Alert/Ansible OK
Phase 3  Détection ML     [#########.]  90%   collector/training/detector OK (51 tests)
Phase 4  Remédiation      [#########.]  90%   moteur + plan d'exécution câblés (105 tests) ; validation live à faire
Phase 5  Dashboard        [#########.]  90%   dashboard branché sur le moteur réel + Prometheus ; validation live à faire
Phase 6  Cyber & attaques [########..]  85%   WAF, SOPS, durcissement, 4 scénarios OK
Phase 7  Assistant RAG    [#########.]  90%   RAG livré (98 tests)
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
| Compose : 4 réseaux + profils + socket-proxy | `infra/compose` | R5,R19,R15 | — | ✅ | `docker-compose.yml` ; **images tierces épinglées (R5, #21 : plus de `:latest`)** |
| SOPS + age + `.sops.yaml` + `.gitignore` | `security/sops` | R13 | Louis | ✅ | README + decrypt-secrets.sh ; `.env` déchiffré ignoré, exemples factices seulement (audit §3-4 OK) |
| gitleaks + ruff pre-commit | `.pre-commit-config.yaml` | R13 | Louis | ✅ | gitleaks v8.18.4 + check-added-large-files ; relancé (config présente) |
| **EBIOS RM v1** (valeurs métier, sources de risque, scénarios) | `docs/ebios-rm.md` | R16 | — | ✅ | docs/ebios-rm.md |
| `docs/architecture.md` + `docs/network.md` + ADR | `docs/` | R19 | — | ✅ | architecture.md, network.md, 3 ADR |

## J2 — Mardi : plateforme, infra, ML

| Tâche | Composant | Réf. | Propriétaire | Statut | Preuve |
|---|---|---|---|---|---|
| auth : login/register, JWT, bcrypt, rate-limit | `services/auth` | R1 | — | ✅ | 35 tests verts (métriques contrat §2) |
| payment-api : comptes, transactions, health/ready, métriques | `services/payment-api` | R1,R2 | — | ✅ | 54 tests verts (+1 skip Postgres) |
| front : login, solde, comptes, virement, historique | `services/front` | R1 | — | ✅ | CDC+README+src+tests ; contrat payment-api réaligné (centimes/ids) ; design « Banque Résilience » intégré (44 tests Vitest verts, lint+build OK, vérifié contre auth/payment-api locaux) |
| seed + verify_tx | `scripts/` | R2 | — | ✅ | **réalignés sur le contrat** (#4/#5) : `verify_tx` résout les ids de comptes via l'API et poste `TransactionIn` (3 entiers) ; seed unique = `resilience_db.seed` (comptes financés, `SEED_PASSWORD` SOPS), `scripts/seed.py` délègue ; 11 tests `scripts/tests` verts ; `scripts/README.md` |
| Observabilité provisionnée (Prom/Loki/Grafana/Alert) | `infra/*` | R7 | — | ✅ | configs + provisioning |
| WAF Nginx+ModSec+CRS devant le front | `security/waf` | R11 | — | 🟨 | `Dockerfile` ajouté (#6 : image CRS épinglée, non-root 8080/8443, TLS auto-signé au build) ; upstream corrigé `front:8080` (#7) ; healthcheck `CMD-SHELL curl -fsk https://127.0.0.1:8443/healthz` (#10 : forme shell, `curl` présent dans l'image CRS, `/healthz` servi sans upstream, testé) ; **`waf-exporter` réel** (#12 : conteneur dédié, audit ModSecurity JSON sur volume `waf-logs`, `/metrics` :9188 sur `obs`, cible Prometheus `waf-exporter:9188`, log `waf_blocked`) ; 25 tests (exporteur : parseur, métrique exposée, suivi du journal ; contrat de config) verts. **Reste : build + smoke live (`make up`) sur une machine avec Docker — vérifier que `waf_blocked_per_s` devient non nul pendant `web_attack`** |
| Durcissement conteneurs (non-root, cap_drop, read_only) | `security/hardening` | R14 | Louis | ✅ | hardening.md + audit.sh **enrichi** (7 contrôles : +exposition réseau WAF-only, +ancre durcissement, +data interne) — exit 0 ; **Postgres non-root** (#11 : `user: "70:70"`, `cap_drop: ALL` sans `cap_add`, choix documenté) + 3 tests contrat `infra/tests/test_compose_hardening.py` — init sur volume vierge à valider live ; **remediation `read_only`+volume journal, `ollama` durci (#22)** |
| collector (features) + training (IsolationForest) | `ml/collector`, `ml/training` | R8 | — | ✅ | 51 tests ML verts |
| EBIOS v2 + début NIS2/DORA | `docs/` | R16,R18 | — | ✅ | ebios-rm.md, nis2-dora.md |

## J3 — Mercredi : détection, remédiation, dashboard, interconnexion

| Tâche | Composant | Réf. | Propriétaire | Statut | Preuve |
|---|---|---|---|---|---|
| detector : score temps réel + émission événement | `ml/detector` | R8 | — | ✅ | detector tests (AnomalyEvent validé) ; **modèle via `make model` + versions sklearn épinglées + garde-fou de dérive (#23)** |
| Moteur de remédiation + table de décision | `remediation/` | R3,R15 | — | ✅ | 105 tests verts (dont exécution réelle du playbook WAF par ansible-runner) ; boot corrigé (#3) ; **plan d'exécution câblé au conteneur** (#8) : `verify_tx` + playbooks embarqués, exécution in-container (`hosts: localhost`), deny-list WAF en volume partagé + reload SIGHUP via le proxy (5e couple), `pg_restore` en direct sur le réseau `data` (client PG 16, dumps ro), variables alignées, inventaire portable. Reste : validation live `make up` (pas de Docker sur le poste de dev) |
| docker-socket-proxy + API authentifiée | `remediation/`, `infra/compose` | R15 | — | ✅ | haproxy strict câblé (5 couples, `kill` limité à `signal=HUP`) + Bearer statique (ADR 0002) |
| Playbooks Ansible (deploy + remédiation) | `infra/ansible` | R6 | — | ✅ | opérateur : deploy, pg_backup, db_corrupt_fake (hôte) ; automate : `playbooks/remediation/{waf_deny_ip,pg_restore}.yml` (in-container) ; `--syntax-check` + run réel en tests ; `infra/ansible/README.md` |
| Alertmanager → webhook remédiation | `infra/alertmanager`, `infra/prometheus/rules`, `remediation/alertmanager.py` | R7 | — | ✅ | **I6 fermé** (#13) : `POST /events/alertmanager` authentifié + adaptateur (13 tests), règles Prometheus miroir + `rule_files`/`alerting`, token Alertmanager via secret Compose (jamais en clair) ; 11 tests contrat `infra/tests`. Validation live (`make up-full`) à faire |
| Règles SOC Loki/Grafana | `infra/grafana`, `infra/loki` | Louis | 🟨 | 4 règles (couvre les 4 incident_type) corrigées (uid datasource, reduce, +data_corruption) ; 5 tests contrat verts ; **routage → remédiation fermé** (#13, voie Prometheus+Alertmanager, voir README-SOC.md) |
| Dashboard (états, score, timeline, MTTD/MTTR, SSE) | `dashboard/` | R4,R20 | — | ✅ | CDC+README+src+tests ; design « ZTR Supervision » ; **branché sur l'enveloppe réelle du moteur** (#9 : adaptateur `event: timeline` → kinds internes, testé sur des trames capturées sur le moteur, aucune trame droppée), score/santé lus dans Prometheus via proxy nginx same-origin (`/prometheus/api/v1/query`, GET seul), compose corrigé (variables runtime, Bearer SOPS, healthcheck) — 121 tests verts, build OK, mock aligné |
| Scénarios d'attaque v1 (depuis PC Attaquant) | `attacks/` | R10 | Louis | ✅ | 4 scénarios ; validateur + runbook PC Attaquant ; déclencheur `data_corruption` (pg_backup + db_corrupt_fake réversible) ; `reset.sh` **revert effectif** (#14 : inventaire explicite, échec Ansible propagé, sans objet si la base ne tourne pas) |
| Console Red Team (UI de pilotage locale) | `attacks/console/` | R10 | Louis | ✅ | FastAPI + UI (lancement, chaîne de reprise, journal SSE, kill-switch, liaison Bleu optionnelle MTTD/MTTR) ; garde-fous côté serveur |
| Campagne multi-étapes (Opération Triade) | `attacks/campaign.sh` | R10 | Louis | ✅ | 3 vagues corrélées auth→web→flood (bornées, réversibles, kill-switch) + bouton console ; teste la corrélation SOC |
| Techniques avancées (rotation, pulse, recon, replay, slow) | `attacks/run.sh`, `attacks/ATTACKS.md` | R10 | Louis | ✅ | 5 techniques éprouvant des facettes ciblées (robustesse remédiation, seuils temporels, largeur détection, intégrité, lenteur) + panneau console + doc pédagogique |
| RAG : indexation docs + journal, UI onglet | `assistant/` | R9 | — | ✅ | 98 tests verts ; **événements déclarés au contrat §1 + allowlist (#24)** |

## J4 — Jeudi : recette, chaos, clip, gel du code (17h)

| Tâche | Composant | Réf. | Propriétaire | Statut | Preuve |
|---|---|---|---|---|---|
| Tests e2e rejouant chaque scénario | `tests/e2e` | R10 | Louis | 🟨 | 4 scénarios couverts (dont data_corruption KO→OK) + preuve incident clos optionnelle ; 5 tests collectés/skip OK hors stack, à valider live |
| Chaos engineering (pannes non-attaque) | `attacks/chaos`, `tests/e2e` | — | Louis | ✅ | `chaos.sh` (crash/freeze, bornés+réversibles, kill-switch) + README ; 5 tests contrat + e2e `test_chaos_flow.py` (skip hors stack) |
| `scripts/demo.sh` (5 temps enchaînés) | `scripts/` | R20 | — | ✅ | scripts/demo.sh |
| PCA/PRA (RTO/RPO, risques résiduels) | `docs/pca-pra.md` | R17 | — | ✅ | docs/pca-pra.md |
| NIS2/DORA finalisé | `docs/nis2-dora.md` | R18 | — | ✅ | docs/nis2-dora.md |
| Dossier PDF 8–12 p | `docs/dossier/` | §7 | — | ✅ | #15 : source `docs/dossier/dossier.md` (13 sections + 2 annexes, synthèse reliée au code : archi, incident, ML, remédiation, sécurité, essais, EBIOS, PCA/PRA, NIS2/DORA, limites, contributions) ; export `build.sh` (markdown → HTML → Chrome headless) → `Workshop2026-M2-G1-Dossier.pdf` **généré : 11 pages** (garde + 9 de corps + 1 d'annexes). **À faire avant remise** : remplir les [M] (MTTD/MTTR mesurés en recette) et les lignes « à compléter » du §13 |
| Slides Pres.pptx | `docs/dossier/slides/` | §7 | — | ✅ | #16 : `build.js` (pptxgenjs, deck structuré : thème, layouts, sections, notes présentateur, graphique natif des tests) → `Workshop2026-M2-G1-Pres.pptx` **généré : 10 slides** (~5 min), validation OOXML OK, contrôle géométrique OK. **À faire avant remise** : relecture visuelle PowerPoint/LibreOffice, [M] de la slide 8, contributions slide 10 |
| **Clip Chrono ≤ 60 s** | `Workshop2026-M2-G1-VidChrono.mp4` | §7 | — | ⬜ | — |
| `Code.zip` (sans secrets) | `scripts/package_deliverables.sh` | §7 | — | ✅ | #18 : archive **générée** (`Workshop2026-M2-G1-Code.zip`, 6,4 Mo, 465 fichiers, audit OK, aucun `.env`/clé ; exclusions `dist`/caches/`egg-info`/dumps/autres livrables ajoutées, re-scan du **contenu** (clé age / clé privée) ; 3 tests `scripts/tests/test_package_deliverables.py` sur faux dépôt ; ignorée par git). À régénérer au gel du code (J4 17h) |
| `make test` = agrégat réel du dépôt | `Makefile`, `README.md` | — | — | ✅ | #19 : un process pytest **par composant** (métriques Prometheus déclarées à l'import → `DuplicateTimeseries` en process unique), `infra/tests` + `tests/e2e` ajoutés, échec propagé (plus de `\|\| echo`), `PYTHON=` surchargeable ; procédure venv documentée (README § Tests) ; 2 tests contrat `scripts/tests/test_makefile.py` ; recette rejouée : 12 composants verts |
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

## Points d'intégration

> ✅ **I6 — fermé** (#13) : routage **SOC → remédiation** câblé et authentifié. Voie retenue : règles Prometheus `infra/prometheus/rules/soc.yml` (miroir des règles Grafana, cohérence testée) → Alertmanager (profil `full`, Bearer via secret Compose `remediation_token`) → `POST /events/alertmanager` (adaptateur `remediation/alertmanager.py` → `AnomalyEvent` §3, rejeu idempotent). Détail : `infra/grafana/provisioning/alerting/README-SOC.md`. Le détecteur reste le chemin principal.

### Câblage initial — réconcilié

| # | Écart | Résolution | Preuve |
|---|---|---|---|
| I1 | Proxy Docker | **haproxy** retenu (liste blanche stricte, 5 couples méthode/chemin) ; tecnativa retiré ; câblé dans compose | ADR 0002 maj, `docker-compose.yml` |
| I2 | Variable verify_tx | compose aligné sur `VERIFY_TX_PATH` | `docker-compose.yml` |
| I3 | Noms de playbooks | `block_ip.yml`→`waf_deny_ip.yml`, `restore_pg_dump.yml`→`pg_restore.yml` ; déplacés dans `playbooks/remediation/` (exécution in-container, #8) | `infra/ansible/playbooks/remediation/` |
| I4 | Auth moteur | **Bearer statique interne** acté (service non exposé) | `contracts.md §API`, ADR 0002 |
| I5 | Métriques HTTP lib | `instrument()` réécrit (middleware) → `resilience_http_requests_total{service,method,path,status}` ; `xfail` retirés ; conftests nettoyés | auth 35/35, payment-api 54/54 |

### Revue P2 — tickets #20 à #24

| # | Écart | Résolution | Preuve |
|---|---|---|---|
| #20 | Docs périmées | Sections « Écarts » des deux services corrigées (lib métriques conforme, tests actifs/verts, plus de `xfail`) ; mentions Tecnativa = comparaisons seulement (archi/nis2/hardening déjà en HAProxy) ; caveats `[S]→[R]` de la gouvernance rafraîchis (compose, 3 playbooks, `verify_tx`, règles SOC, tests remediation livrés) — restent `[S]` : clé age réelle/`secrets.enc.env`, planification du dump, copie hors hôte | `services/{auth,payment-api}`, `docs/{ebios-rm,pca-pra,nis2-dora}.md` |
| #21 | Reproductibilité R5 | Toutes les images tierces épinglées (plus aucun `:latest`) — Prometheus/Loki/Promtail/Grafana/Alertmanager/cAdvisor/pg-exporter/Ollama/curl | `docker-compose.yml`, test `test_image_tags_are_pinned_for_reproducibility`. **Live `make up-full` à rejouer sur machine Docker** |
| #22 | Durcissement moteur + Ollama | remediation `read_only: true` + volume nommé `remediation-journal` (journal SQLite persistant, conforme CDC §5.4) ; ancre de durcissement appliquée à `ollama` (`no-new-privileges` + `cap_drop: ALL`) | `docker-compose.yml`, `hardening.md`, tests `test_remediation_container_matches_read_only_claim` + `test_hardening_anchor_applied_to_every_service` |
| #23 | Image detector non buildable | Étape documentée et dans `make` : `make up`/`up-full` dépendent de `make model` (entraîne si artefact absent) ; `scikit-learn==1.9.1`/`numpy`/`joblib` épinglés à l'identique training↔detector (`ml/training/requirements.txt`) ; garde-fou : événement JSON réservé `model_version_drift` (contrat §1) journalisé si la version sklearn chargée diffère de `baseline_stats.json` | `Makefile`, `ml/detector/{model.py,README.md}`, `docs/contracts.md §1`, test `test_load_model_warns_on_sklearn_version_drift` (51 tests ML verts) |
| #24 | Hygiène + événements hors contrat | `egg-info` déjà non suivi + ignoré (`.gitignore`) ; 3 événements assistant (`assistant_index_empty`/`_store_error`/`_http_request`) déclarés au contrat §1 + allowlist `resilience_common.RESERVED_EVENTS` ; tests de conformité contrat↔allowlist et assistant↔allowlist | `docs/contracts.md §1`, `resilience_common/events.py`, tests `test_reserved_events_match_contract_table` + `test_assistant_emits_only_reserved_events` |

### Revue P3 — polissage final (blindage jury)

> Ronde de sévérité la plus basse : cohérence doc, hygiène lint, durcissement de finition. Aucun changement de contrat. Suite complète rejouée verte (voir preuves). Issue de deux revues (transverse + sécurité).

| # | Écart | Résolution | Preuve |
|---|---|---|---|
| P3-1 | Garde de périmètre offensif absente (CLAUDE.md : « pas d'action hors réseau du projet ») | `run.sh` et la console refusent (fail closed) toute cible dont l'hôte n'est pas dans la liste blanche `192.168.137.1 127.0.0.1 localhost waf` ; surchargeable par `ATTACK_ALLOWED_HOSTS` ; `campaign.sh` couvert (délègue à `run.sh`) | `attacks/run.sh`, `attacks/console/server.py` (`validate_target`), test `test_offperimeter_target_is_rejected` (attacks : 31 tests) |
| P3-2 | `front` non `read_only` alors qu'il peut l'être (nginx n'écrit que `/tmp`) | `read_only: true` + `tmpfs: ["/tmp"]` (parité avec `dashboard`) | `docker-compose.yml`, `hardening.md` ; `audit.sh` OK |
| P3-3 | Grafana : repli silencieux sur `admin` si `GRAFANA_PASSWORD` absent | `${GRAFANA_PASSWORD:?…}` (échec bruyant, plus de défaut `admin`) ; secret **requis** déclaré (`secrets.example.env`, `security/sops/README.md`) — **à ajouter à `secrets.enc.env` avant `make up`** | `docker-compose.yml:302`, `security/sops/{secrets.example.env,README.md}` |
| P3-4 | Commentaires de durcissement trompeurs ou périmés | `:ro` sur un socket Unix ne limite aucun appel d'API (la liste blanche haproxy, si) : commentaires du socket (proxy/promtail/cadvisor) corrigés ; `nginx.conf` WAF : l'audit ModSecurity va dans `/var/log/modsec/audit.json` (pas stdout) ; `hardening.md` : `audit.sh` ne vérifie pas `USER` (→ revue Dockerfile), `cpus` seulement sur les services Python | `docker-compose.yml`, `security/waf/nginx.conf`, `security/hardening/hardening.md` |
| P3-5 | Hygiène lint (hook pre-commit non joué) | Imports triés (I001, 20 fichiers, via ruff 0.6.9 épinglé) ; import mort `ActionSpec` retiré (`engine.py`) ; `import os`/variable `m` inutilisés retirés ; `l`→`entry` (E741) | `ruff check --select I,F401,F841` vert ; suite complète verte |
| P3-6 | Compteurs de tests périmés (preuve jury) | Réalignés sur la réalité mesurée : remédiation 91→**105**, assistant 97→**98**, ML 50→**51**, WAF 14→**25** | `ROADMAP.md`, `ml/README.md`, `security/waf/CAHIER-DES-CHARGES.md` |

## Risques projet (vivant)

| Risque | Impact | Parade | Statut |
|---|---|---|---|
| RAM 16 Go saturée par Ollama + stack | démo qui rame | Ollama sur PC IA ; profil Compose « démo » minimal | surveillé |
| ML instable sur 60 s | démo ratée (Axe 1) | dataset baseline solide + seuil de secours documenté comme limite | surveillé |
| Attaque pas prête sur 2e PC | perte Axe 1 | profil `attack` en secours, mais viser le 2e PC tôt | surveillé |
| Déploiement non reproductible | pénalité §3.2 | Ansible + README testés sur machine vierge | surveillé |
