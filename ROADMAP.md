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
Phase 3  Détection ML     [#########.]  90%   outillage données réelles OK (77 tests 3.12, build vérifié) ; capture réelle à jouer
Phase 4  Remédiation      [######....]  60%   code + CDC + README ; câblage à réconcilier
Phase 5  Dashboard        [########..]  85%   dashboard + front livrés (src+tests)
Phase 6  Cyber & attaques [########..]  85%   WAF conteneurisé, testé sur la vraie image ; e2e web_attack (blocage IP auto, I11) à faire
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
| seed + verify_tx | `scripts/` | R2 | — | ✅ | scripts/verify_tx, scripts/seed.py ; `scripts/tests/test_verify_tx.py` (I8) |
| Observabilité provisionnée (Prom/Loki/Grafana/Alert) | `infra/*` | R7 | — | ✅ | configs + provisioning |
| WAF Nginx+ModSec+CRS devant le front | `security/waf` | R11 | — | 🟨 | image OWASP CRS 4 LTS épinglée, non-root ; `security/waf/tests` : 59 verts dont 13 sur la **vraie image** (`make test-waf` : CRS 403, blocklist par renommage + reload, XFF écrasé, routes internes 404, rotation du journal, cause des 502) ; revue security-reviewer traitée ; **reste avant ✅** : `/api/v1/*` → 200 (stack complète, I12) et e2e `web_attack` vert (bloqué par I11) |
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
| ML sur vraies séries Prometheus : outillage (capture, train `--data`, calibration seuil + MTTD, trafic légitime, train au build) | `ml/*`, `scripts/gen_normal_traffic.py` | R8 | — | ✅ | `make test-ml` : 77 verts en Python 3.12.15 (sklearn 1.9.1, numpy 2.5.4) + scripts 15 verts ; `docker compose build detector` OK ; review PR #2 traitée |
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
| I7 | Build image detector | le Dockerfile copiait des artefacts non versionnés (build impossible) -> modèle entraîné au build ; seuil calibré périmé = build en échec | `docker compose build detector` OK (non-root uid 10003, sha256 vérifié) ; empreinte fausse -> build en échec code 3, bonne -> seuil calibré appliqué |
| I9 | WAF jamais conteneurisé | pas de Dockerfile (build `make up` impossible), exporter sans serveur ni suivi du journal, nginx.conf incompatible non-root, front visé sur le port 80 au lieu de 8080 -> image OWASP CRS + modèles, service `waf-exporter`, ports `80:8080`/`443:8443` | `security/waf/`, vérifié stack levée |
| I10 | Label Loki de `waf_blocked` | l'event est émis par le service `waf-exporter` : requêtes `{service="waf"}` du detector et de `confirm_waf_block` corrigées | `ml/detector/events.py`, `remediation/actions/waf.py` (tests) |
| I11 | 🔴 Chaîne auto `waf_block_ip` | ~~playbook `blocked_ip` vs moteur `deny_ip`~~ **corrigé** (playbook lit `deny_ip`, test d'alignement) ; ~~bind mount du fichier de liste~~ **corrigé** (dossier `security/waf/blocklist/` monté, écriture par renommage vue par nginx, testé sur la vraie image). **Reste** : `docker exec … nginx -s reload` interdit par `docker-socket-proxy` ; le detector n'émet pas `source_ip`. L'action n'est pas vérifiée de bout en bout | **à corriger** |
| I12 | ✅ Services qui ne démarrent pas | **postgres** : `cap_drop: ALL` empêchait le `chown`/`gosu` de l'entrypoint (=> auth, payment-api KO) -> `user: postgres` + `read_only` + tmpfs, **aucun `cap_add`** ; **remediation** : `http_metrics.py` redéclarait `resilience_http_requests_total` (DuplicateTimeseries) -> réutilise les objets de `resilience_common.metrics` ; **dashboard** : CRLF au checkout Windows -> `.gitattributes` (LF sur scripts, entrypoints, `verify_tx`, Dockerfiles, confs) + `sed` garde-fou au build ; **grafana** (trouvé en route) : règles SOC sans `relativeTimeRange` et `datasourceUid` sans source correspondante -> `relativeTimeRange` + `uid` provisionnés | stack `demo`+`full` : 18/18 services up, tous les healthchecks `healthy`, 0 redémarrage ; `make seed` 3 comptes ; remediation 80/80 (dont `test_api`) ; Grafana : 3 règles et 2 sources chargées |
| I13 | 🟨 IP source en Docker Desktop | le WAF voit les clients de l'hôte sous l'IP de passerelle `edge` (ex. 172.22.0.1) : blocklist et rate-limit de l'auth viseraient tout le monde si c'est aussi le cas depuis le PC attaquant | à vérifier depuis le PC attaquant |
| I14 | 🟨 Segmentation réseau | WAF sur `app` avec `docker-socket-proxy` (sans auth) et `remediation` : sans effet via la conf nginx, mais joignable au niveau L3 si le WAF était compromis -> réseau `ctl` dédié proxy+remédiation | à planifier (R19) |
| I8 | ✅ `verify_tx` vs payment-api | `verify_tx` envoyait `dst_account` = IBAN (chaîne) sans `src_account` ; l'API attend des **ids entiers** (`StrictInt`) -> 422 systématique (même défaut dans `attacks/run.sh` service_flood, qui en plus n'envoyait aucun jeton : 401 avant Postgres) -> `verify_tx` lit l'id source (`GET /accounts`), le destinataire via `VERIFY_DST_ID` / l'historique / `demo02`, et exige que la transaction `created` figure dans l'historique ; le flood se connecte et envoie des ids entiers (1 centime). Reste le solde nul : voir I15 | `scripts/tests/test_verify_tx.py` 13/13 (corps validé par le vrai `TransactionIn`), `attacks/tests/test_run_flood.py` 3/3 ; stack réelle : ancien script 422, nouveau 409 `insufficient_funds` (schéma OK, comptes 1 -> 2 résolus) |
| I15 | ✅ Comptes seedés sans solde | `seed.py` envoie `iban_fake`/`balance_cents`, ignorés par `register` (IBAN aléatoire, `REGISTER_INITIAL_BALANCE_CENTS` = 0 par défaut, non défini dans compose) : tout virement répond 409 `insufficient_funds`, donc `verify_tx` reste KO et la boucle Zero-Touch ne peut pas conclure. Le conteneur `remediation` n'a pas non plus de `BASE_URL` : `verify_tx` y vise `https://localhost` au lieu du WAF. **Et `verify_tx` n'était pas copié dans l'image remediation** (ni `/app/verify_tx` du compose, ni `/opt/scripts/verify_tx` du Dockerfile) -> `REGISTER_INITIAL_BALANCE_CENTS=100000` pour auth, `BASE_URL=https://waf:8443` pour remediation, `COPY scripts/verify_tx /opt/scripts/verify_tx` (override de chemin du compose retiré) | `remediation/tests/test_compose_wiring.py` 3/3 (3 échecs sans le correctif) ; stack réelle (base réinitialisée) : `make seed` 3 comptes / 3 000 €, `make verify` rc=0, `verify_tx` depuis le conteneur remediation via le WAF rc=0 |
| I5 | Métriques HTTP lib | `instrument()` réécrit (middleware) → `resilience_http_requests_total{service,method,path,status}` ; `xfail` retirés ; conftests nettoyés | auth 35/35, payment-api 54/54 |

## Risques projet (vivant)

| Risque | Impact | Parade | Statut |
|---|---|---|---|
| RAM 16 Go saturée par Ollama + stack | démo qui rame | Ollama sur PC IA ; profil Compose « démo » minimal | surveillé |
| ML instable sur 60 s | démo ratée (Axe 1) | dataset baseline solide + seuil de secours documenté comme limite | surveillé |
| Attaque pas prête sur 2e PC | perte Axe 1 | profil `attack` en secours, mais viser le 2e PC tôt | surveillé |
| Déploiement non reproductible | pénalité §3.2 | Ansible + README testés sur machine vierge | surveillé |
