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
Phase 3  Détection ML     [#########.]  90%   collector/training/detector OK + outillage données réelles (capture/calibration)
Phase 4  Remédiation      [#########.]  90%   moteur + plan d'exécution câblés (106 tests) ; validation live à faire
Phase 5  Dashboard        [#########.]  90%   dashboard branché sur le moteur réel + Prometheus ; validation live à faire
Phase 6  Cyber & attaques [########..]  85%   WAF, SOPS, durcissement, 4 scénarios OK
Phase 7  Assistant RAG    [#########.]  90%   RAG livré (98 tests)
Phase 8  Gouvernance      [########..]  80%   EBIOS/PCA/NIS2 rédigés, reliés à l'archi
Phase 9  Consigne add. 1  [#####.....]  50%   L0+L1+L2 faits + L3 login (49+15+14 tests) ; reste habilitations + câblage LED/infra + gouvernance
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
| auth : login/register, JWT, bcrypt, rate-limit | `services/auth` | R1 | — | ✅ | 36 tests verts (métriques contrat §2) |
| payment-api : comptes, transactions, health/ready, métriques | `services/payment-api` | R1,R2 | — | ✅ | 65 tests verts (+1 skip Postgres) |
| Test de charge payment-api (débit/latence/portes SLO) | `services/payment-api/loadtest` | R2,R17 | — | ✅ | générateur de charge in-process (ASGI/SQLite WAL, sans Docker) + mode live `--url`/`--auth-url` (login auth ≠ API payment-api) ; rapport p50/p95/p99 + export JSON + portes SLO (code 2) ; **profil par défaut : 0 erreur** ; 11 tests fumée `tests/test_loadtest_smoke.py` verts (dont régressions `--mix` write-only, garde `-c 0`, `-n` prime sur `-d`). CDC + README. Baseline « charge normale » vs `service_flood` ; **chiffres de capacité officiels à mesurer en recette (`--url` sur stack PostgreSQL), à reporter dans `docs/pca-pra.md §4.3`** |
| front : login, solde, comptes, virement, historique | `services/front` | R1 | — | ✅ | CDC+README+src+tests ; contrat payment-api réaligné (centimes/ids) ; **refonte maquettes Claude Design desktop + mobile** (#37–#41 : shell barre latérale/onglets, accueil, statistiques, envoi formulaire + assistant 4 étapes « glisser pour envoyer », historique + export CSV, détail d’opération, RIB, profil) et **bandeau d’état du service** côté front (#42 : perturbé → rétabli sans action, rafraîchissement 15 s) ; 59 tests Vitest verts, lint+typecheck+build OK, rendu vérifié en navigateur desktop 1280 et mobile 390 |
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
| Moteur de remédiation + table de décision | `remediation/` | R3,R15 | — | ✅ | 106 tests verts (dont exécution réelle du playbook WAF par ansible-runner) ; boot corrigé (#3) ; **plan d'exécution câblé au conteneur** (#8) : `verify_tx` + playbooks embarqués, exécution in-container (`hosts: localhost`), deny-list WAF en volume partagé + reload SIGHUP via le proxy (5e couple), `pg_restore` en direct sur le réseau `data` (client PG 16, dumps ro), variables alignées, inventaire portable. Reste : validation live `make up` (pas de Docker sur le poste de dev) |
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
| ML sur vraies séries Prometheus : outillage (capture, train `--data`, calibration seuil + MTTD, trafic légitime, train au build) | `ml/*`, `scripts/gen_normal_traffic.py` | R8 | — | ✅ | outillage capture/calibration + tests verts ; `ml/training/README.md` §6 |
| ML sur vraies séries : capture baseline + scénarios, calibration, rebuild detector | `ml/training/data/` | R8 | — | ✅ | baseline réelle 60 min (241 fenêtres) + `service_flood`, `auth_abuse`, `web_attack` ; seuil calibré 0,7173 (normal max 0,692, 0 % faux positifs), MTTD modèle 15 s par scénario ; chaque fenêtre en alerte routée vers le bon type. Corrigé en route : débit réel de `run.sh` sous Git Bash, cible des captures, flood authentifié (I8), `auth_failed_per_s` (+ refus du rate-limit), cpu/mem limités à la plateforme. Capturé et vérifié (detector reconstruit, e2e `web_attack` déclenché par le modèle) sur la stack de `feat/waf-block-chain` : **à rejouer sur cette base** (`make test-ml`, build du detector, e2e). **Non capturé** : `data_corruption` (déclenché côté opérateur, hors `run.sh`) |
| `scripts/demo.sh` (5 temps enchaînés) | `scripts/` | R20 | — | ✅ | scripts/demo.sh |
| PCA/PRA (RTO/RPO, risques résiduels) | `docs/pca-pra.md` | R17 | — | ✅ | docs/pca-pra.md |
| NIS2/DORA finalisé | `docs/nis2-dora.md` | R18 | — | ✅ | docs/nis2-dora.md |
| Dossier PDF 8–12 p | `docs/dossier/` | §7 | — | ✅ | #15 : source `docs/dossier/dossier.md` (13 sections + 2 annexes, synthèse reliée au code : archi, incident, ML, remédiation, sécurité, essais, EBIOS, PCA/PRA, NIS2/DORA, limites, contributions) ; export `build.sh` (markdown → HTML → Chrome headless) → `Workshop2026-M2-G1-Dossier.pdf` **généré : 11 pages** (garde + 9 de corps + 1 d'annexes). **À faire avant remise** : remplir les [M] (MTTD/MTTR mesurés en recette) et les lignes « à compléter » du §13 |
| Slides Pres.pptx | `docs/dossier/slides/` | §7 | — | ✅ | #16 : `build.js` (pptxgenjs, deck structuré : thème, layouts, sections, notes présentateur, graphique natif des tests) → `Workshop2026-M2-G1-Pres.pptx` **généré : 10 slides** (~5 min), validation OOXML OK, contrôle géométrique OK. **À faire avant remise** : relecture visuelle PowerPoint/LibreOffice, [M] de la slide 8, contributions slide 10 |
| **Clip Chrono ≤ 60 s** | `Workshop2026-M2-G1-VidChrono.mp4` | §7 | — | 🟨 | **Kit de production livré et testé** (#C1) : `docs/dossier/clip/` = storyboard (contrat JSON : 5 temps, budget ≤ 60 s, prise unique sans coupe) + `gen_ass.py` (légendes échappées, temps validés) + `build_clip.sh` (recadrage + incrustation + garde-fou durée ffprobe, sortie temporaire + `mv`) + runbook ; 6 tests `scripts/tests/test_clip_chrono.py` verts (budget, 5 temps ordonnés/contigus, `gen_ass` exécuté : 1 ligne/temps, anti-injection). **Reste : enregistrer le `.mp4` en recette J4** (stack levée + PC Attaquant) — le MP4 est du footage live, non synthétisable hors stack |
| `Code.zip` (sans secrets) | `scripts/package_deliverables.sh` | §7 | — | ✅ | #18 : archive **générée** (`Workshop2026-M2-G1-Code.zip`, 6,4 Mo, 465 fichiers, audit OK, aucun `.env`/clé ; exclusions `dist`/caches/`egg-info`/dumps/autres livrables ajoutées, re-scan du **contenu** (clé age / clé privée) ; 3 tests `scripts/tests/test_package_deliverables.py` sur faux dépôt ; ignorée par git). À régénérer au gel du code (J4 17h) |
| `make test` = agrégat réel du dépôt | `Makefile`, `README.md` | — | — | ✅ | #19 : un process pytest **par composant** (métriques Prometheus déclarées à l'import → `DuplicateTimeseries` en process unique), `infra/tests` + `tests/e2e` ajoutés, échec propagé (plus de `\|\| echo`), `PYTHON=` surchargeable ; procédure venv documentée (README § Tests) ; 2 tests contrat `scripts/tests/test_makefile.py` ; recette rejouée : 12 composants verts |
| **Gel du code 17h** | `docs/FREEZE-J4.md` | §7 | — | 🟨 | **Runbook de gel livré** (#C2) : checklist J4 (arbre propre → tests verts → recette live → régénération des 4 livrables depuis le commit → tag ciblé `freeze-j4`), garde-fous « on ne gèle pas si rouge ». Archive **régénérée et vérifiée** (`Workshop2026-M2-G1-Code.zip`, audit + re-scan secrets OK, kit Clip inclus, prises brutes exclues). **Reste : jouer la checklist à J4 17h** (poser le tag sur une machine Docker) |

## Phase 9 — Consigne Additionnelle 1 : renforcement auth back-office (visage + LED)

> Consigne reçue le 2026-10-20 (EPSI). **Cadrage complet : [`docs/consigne-additionnelle-1.md`](docs/consigne-additionnelle-1.md)** · **backlog détaillé et suivi : [`docs/consigne-additionnelle-1-roadmap.md`](docs/consigne-additionnelle-1-roadmap.md)** (10 lots, ~30 tickets, DoD par ticket). Le tableau ci-dessous est le **résumé** ; le suivi fin se fait dans le backlog dédié.

| Lot | Objet | Composant(s) | Statut | Preuve |
|---|---|---|---|---|
| L0 | Delta contrat + ADR 0004/0005/0006 + modèle données (rôles, `face_enrollments`) | `docs/contracts.md`, `docs/adr`, `resilience_db` | ✅ | contrat §5 + migration `0002` ; tests verts |
| L1 | Service `face-id` (IA légère, reconnaissance 1:1, enrôlement) | `services/face-id` | ✅ | service + **10 tests verts** ; smoke modèle réel en recette |
| L2 | Auth à étapes (identifiant→visage→mdp) + verrouillage 1 reprise/5 min **[critique]** | `services/auth` | ✅ | 13 tests (49 auth au total) ; LED fail-open + rôle dans le JWT |
| L3 | Back-office React + capture webcam (`getUserMedia`, caméra PC Hôte) **[critique]** | `services/backoffice` | 🟨 | login à étapes + webcam + miroir LED livrés (14 tests) ; reste habilitations (L6) |
| L4 | Firmware ESP8266 LED bicolore (CLion/PlatformIO, machine à états) | `iot/esp8266-led` | 🟨 | modules LED/Wi-Fi/HTTP/MQTT séparés, 3 routes HTTP ; build ESP8266 + 6 tests native verts ; recette matérielle |
| L5 | Transport MQTT (broker Mosquitto durci + client auth fail-open) | `infra/compose`, `services/auth` | 🟨 | service Compose profil `iot` + ACL + mots de passe tmpfs, smoke broker/auth→led réussi ; client MQTT de `auth` à câbler |
| L6 | Habilitations (rôles + enrôlement/révocation visage) | `services/{auth,face-id,backoffice}` | ⬜ | backlog L6 |
| L7 | Infra & observabilité (compose, Prometheus, SOPS, durcissement) | `infra/*`, `security/sops` | ⬜ | backlog L7 |
| L8 | Sécurité & RGPD (biométrie, surface MQTT/caméra, pas de bypass) | `security/*`, `services/face-id` | ⬜ | backlog L8 |
| L9 | Gouvernance (EBIOS biométrie, PCA/PRA break-glass, NIS2/DORA accès) | `docs/{ebios-rm,pca-pra,nis2-dora}.md` | ⬜ | backlog L9 |
| L10 | Recette & e2e (flux complet + **ZTR inchangé** + checklist matériel) | `tests/e2e`, `docs/` | ⬜ | backlog L10 |

> **Garde-fou résilience (D4) :** le facteur visage/LED ne s'applique qu'à l'**accès privilégié** du back-office. La boucle Zero-Touch Recovery (`verify_tx`, détection, remédiation) et le Clip Chrono **ne dépendent jamais** de la caméra/du visage/du broker/de l'ESP — pas d'auto-DoS de la démo notée.

---

## Journal de décisions (ADR)

Décisions d'architecture structurantes : voir `docs/adr/`. Résumé rapide :

| Date | Décision | Statut |
|---|---|---|
| J1 | Mono-langage Python/FastAPI | acté |
| J1 | SOC = règles Loki/Grafana (pas Wazuh par défaut) | acté |
| J1 | Remédiation via docker-socket-proxy, jamais le socket brut | acté |
| J1 | Attaque depuis PC physique pour la démo (profil `attack` = dev) | acté |
| Consigne 1 | Back-office = app dédiée `services/backoffice` (ADR 0004) | cadré |
| Consigne 1 | Caméra USB lue dans le navigateur de l'hôte, pas montée dans Docker (ADR 0005) | cadré |
| Consigne 1 | LED pilotée via MQTT, auth publie des états, le firmware rend les motifs ; facteur visage limité à l'accès privilégié (ADR 0006) | cadré |

## Points d'intégration

> ✅ **I6 — fermé** (#13) : routage **SOC → remédiation** câblé et authentifié. Voie retenue : règles Prometheus `infra/prometheus/rules/soc.yml` (miroir des règles Grafana, cohérence testée) → Alertmanager (profil `full`, Bearer via secret Compose `remediation_token`) → `POST /events/alertmanager` (adaptateur `remediation/alertmanager.py` → `AnomalyEvent` §3, rejeu idempotent). Détail : `infra/grafana/provisioning/alerting/README-SOC.md`. Le détecteur reste le chemin principal.

### Câblage initial — réconcilié

| # | Écart | Résolution | Preuve |
|---|---|---|---|
| I1 | Proxy Docker | **haproxy** retenu (liste blanche stricte, 5 couples méthode/chemin) ; tecnativa retiré ; câblé dans compose | ADR 0002 maj, `docker-compose.yml` |
| I2 | Variable verify_tx | compose aligné sur `VERIFY_TX_PATH` | `docker-compose.yml` |
| I3 | Noms de playbooks | `block_ip.yml`→`waf_deny_ip.yml`, `restore_pg_dump.yml`→`pg_restore.yml` ; déplacés dans `playbooks/remediation/` (exécution in-container, #8) | `infra/ansible/playbooks/remediation/` |
| I4 | Auth moteur | **Bearer statique interne** acté (service non exposé) | `contracts.md §API`, ADR 0002 |
| I6 | Detector -> remédiation | compose : `REMEDIATION_URL` sans `/events` (chaque événement en 404) -> URL complète | `ml/detector/tests/test_compose_wiring.py` |
| I7 | Build image detector | le Dockerfile copiait des artefacts non versionnés (build impossible) -> modèle entraîné au build | `ml/detector/Dockerfile` (étape `trainer`) |
| I8 | 🔴 `verify_tx` vs payment-api | `verify_tx` envoie `dst_account` = IBAN (chaîne) sans `src_account` ; l'API attend des **ids entiers** (`StrictInt`) -> 422 : la vérification de reprise échoue toujours (même défaut dans `attacks/run.sh` service_flood). `seed.py` envoie `iban_fake`/`balance_cents`, ignorés par `register` (IBAN aléatoire, solde par défaut) | **à corriger** |
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

### Revue P4 — finition (cohérence doc + durcissements mineurs)

> Ronde de sévérité la plus basse, issue de deux revues (transverse + sécurité). Correctifs code testés (remédiation 105→**106**, auth 35→**36**) et alignements doc/config sans changement de contrat. Les points d'architecture non vérifiables hors stack (pas de Docker sur le poste) sont corrigés en doc et portés comme risques résiduels (`docs/ebios-rm.md §5.3`). Suite complète rejouée verte : **12 composants Python** + front (44) + dashboard (121).

| # | Écart | Résolution | Preuve |
|---|---|---|---|
| P4-01 | Compteur de tests WAF périmé (5) dans la gouvernance | Réaligné sur 25 | `docs/nis2-dora.md`, `docs/ebios-rm.md`, `docs/cadrage-cyber.md` |
| P4-02 | Commande `pytest attacks/tests` annoncée « 4 tests » (répertoire = 31) | Commandes ciblées sur `attacks/tests/test_scenarios.py` (4 scénarios) | `docs/nis2-dora.md`, `attacks/RUNBOOK-PC-ATTAQUANT.md` |
| P4-03 | Table §3 : `service_flood` annonce « rate-limit » absent de la table de décision | Ligne alignée sur le code (`blocage IP source + redémarrage`) | `docs/contracts.md §3` |
| P4-04 | Métrique `resilience_mttd_seconds` décrite « Mean Time To Detect » alors qu'elle mesure détection→1ʳᵉ action | HELP et description du contrat reformulées (nom de métrique figé, inchangé) | `libs/.../metrics.py`, `docs/contracts.md §1` |
| P4-05 | README : `architecture.md` marqué « (à venir) » alors qu'il existe | Mention retirée | `README.md` |
| P4-06 | Exemple JSON §3 : `loki_query` de `service_flood` = `db_error` (signal de corruption) | Aligné sur le détecteur (`http_status`) | `docs/contracts.md §3`, cohérent avec `ml/detector/events.py` |
| P4-07 | README : sections « Installation » et « Vérifier le système » en placeholder | Remplies (make up/seed/verify/demo, WAF, comptes fictifs) | `README.md` |
| P4-08 | Format d'IBAN fictif de la doc ≠ code | Aligné sur `seed.py` (`FR76 0000 0000 000N 0000 0000 000`) | `scripts/README.md` |
| P4S-05 | `never_block_ips` contournable en IPv4-mappée (`::ffff:a.b.c.d`) | Normalisation canonique avant comparaison (IP et liste blanche) + test | `remediation/actions/waf.py`, `test_engine.py` |
| P4S-09a | Remédiation : `X-Request-ID` entrant accepté tel quel (log-forging) alors qu'auth/payment-api exigent un UUID | Validation UUID à parité + test | `remediation/main.py`, `test_api.py` |
| P4S-04 | `/register` sans rate-limit (flood de comptes, DoS bcrypt, énumération) | `@limiter.limit` (défaut 10/min, `REGISTER_RATE_LIMIT`) + test | `services/auth/.../{main,config}.py`, `test_auth_ratelimit.py` |
| P4S-02 | `obs`/`app` annoncés `internal` mais seul `data` l'était | `obs` passé en `internal: true` ; `app` documenté « non interne » (seule sortie, pull d'images/modèles) ; contrôle 7 d'`audit.sh` étendu à `obs` | `docker-compose.yml`, `docs/network.md`, `audit.sh` (exit 0) |
| P4S-08 | Secrets déchiffrés hors du filet de sécurité | `umask 077` avant `sops --decrypt` ; `.remediation_token`/`*.env.dec` ajoutés à `.gitignore`, aux exclusions et au contrôle final de l'archive ; commentaire compose corrigé | `decrypt-secrets.sh`, `package_deliverables.sh`, `.gitignore`, `docker-compose.yml` |
| P4S-10 | `audit.sh` [3] filtre chemin inclus (fichiers « test/latest » exemptés) ; `trivy` cible une image inexistante | Filtre sur contenu seul + `.sh/.conf/.json` + `--exclude-dir tests` ; commande `trivy` corrigée | `audit.sh` (exit 0), `hardening.md` |
| P4S-06/03 | Doc : « aucun secret en image » (clé TLS figée) et audit WAF | Exception de labo documentée (clé TLS), nuance `read_only`, résiduel journal d'audit WAF | `hardening.md`, `docs/ebios-rm.md §5.3` |
| P4S-01/07 | Résiduels non corrigeables hors stack : passerelle Alertmanager non authentifiée, HTTP clair/TLS | Portés comme risques résiduels + commentaire compose ; génération hex des secrets (évite de casser l'URL du pg-exporter) | `docs/ebios-rm.md §5.3`, `docker-compose.yml`, `security/sops/secrets.example.env` |

## Risques projet (vivant)

| Risque | Impact | Parade | Statut |
|---|---|---|---|
| RAM 16 Go saturée par Ollama + stack | démo qui rame | Ollama sur PC IA ; profil Compose « démo » minimal | surveillé |
| ML instable sur 60 s | démo ratée (Axe 1) | dataset baseline solide + seuil de secours documenté comme limite | surveillé |
| Attaque pas prête sur 2e PC | perte Axe 1 | profil `attack` en secours, mais viser le 2e PC tôt | surveillé |
| Déploiement non reproductible | pénalité §3.2 | Ansible + README testés sur machine vierge | surveillé |
