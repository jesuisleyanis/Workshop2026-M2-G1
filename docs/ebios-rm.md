# Analyse de risques EBIOS Risk Manager — RESILIENCE-ALPHA

> Couvre **R16**. Version **v1 (J1, 2026-10-19)**, à réviser après la recette (J3/J4) avec les MTTR mesurés.
> Périmètre : plateforme de paiement **fictive** d'une entité financière fictive, telle que décrite dans `CAHIER-DES-CHARGES.md` §4 et `docs/contracts.md`. Aucune donnée réelle.

**Légende de statut des mesures (honnêteté de preuve)** : **[R]** réalisé et présent dans le dépôt au 2026-10-19 · **[S]** spécifié (contrat / CDC) mais composant pas encore livré · **[M]** valeur à mesurer en recette.
État du dépôt au 2026-10-19 : `services/*`, `ml/*`, `remediation/*`, `security/*`, `attacks/*`, `infra/*` (dont `infra/compose`, les playbooks Ansible `waf_deny_ip.yml`, `pg_restore.yml`, `pg_backup.yml`, les règles SOC Prometheus/Grafana), `dashboard/` et `scripts/verify_tx` existent. Restent à livrer : la clé age réelle et `secrets.enc.env`, la planification périodique du dump et la copie hors hôte des dumps.

---

## Atelier 1 — Cadrage et socle de sécurité

### 1.1 Valeurs métier (VM)

| Id | Valeur métier | Critère de sécurité dominant | Où elle vit dans l'architecture |
|---|---|---|---|
| **VM1** | **Service de paiement** : initier et traiter un virement fictif (`POST /api/v1/transactions`) | Disponibilité | front -> WAF -> `payment-api` -> Postgres |
| **VM2** | **Intégrité des transactions et des soldes** (grand livre) | Intégrité | `payment_api/ledger.py` (virement atomique, verrou de ligne), contrainte `ck_accounts_balance_non_negative` |
| **VM3** | **Continuité et capacité de reprise autonome** (revenir à un état utilisable prouvé par `verify_tx`) | Disponibilité, preuve | remédiation, détection ML, observabilité |
| **VM4** | **Confiance dans les accès** : identités, sessions JWT (HS256, 15 min), secrets d'exploitation | Confidentialité, intégrité | `services/auth`, SOPS/age, `JWT_SECRET`, `REMEDIATION_TOKEN`, `INTERNAL_TOKEN` |

### 1.2 Échelles de cotation

| Niveau | Gravité (impact sur VM) | Vraisemblance |
|---|---|---|
| 1 | **Mineure** : dégradation < 1 min, aucune donnée touchée | **Minime** : moyens ou accès rares |
| 2 | **Significative** : indisponibilité <= 5 min, sans perte de données | **Possible** : requiert un pré-requis (accès, faille) |
| 3 | **Grave** : indisponibilité > 5 min (reprise manuelle), ou perte bornée de transactions, ou prise de compte | **Vraisemblable** : outils publics, surface exposée |
| 4 | **Critique** : altération/perte de données financières non bornée, compromission d'un secret racine ou de l'automate, arrêt > 1 h | **Quasi certaine** : triviale, automatisable, rejouée au labo |

Niveau de risque = G x V : **<= 4 Faible** · **6-8 Moyen** · **9-12 Élevé** · **16 Critique**. Règle de décision : tout risque Élevé ou Critique doit être traité ; un risque Moyen résiduel est accepté seulement par décision explicite de la direction, avec indicateur de surveillance.

### 1.3 Coût de l'arrêt d'une fonction de paiement (sujet §3.5)

Modèle : `Coût(t) = manque à gagner direct (tx/min x revenu/tx) + coûts indirects (SLA, charge d'exploitation, confiance) + coût réglementaire (incident majeur DORA/NIS2)`.
Ordre de grandeur **pédagogique** (hypothèses fictives, à valider par la direction) : charge nominale ~20 req/s (`ml/training/artifacts/baseline_stats.json`, baseline synthétique), H2 : 1 requête sur 5 est une transaction (240 tx/min), H3 : 0,25 EUR de revenu par transaction -> **~60 EUR/min** direct, soit ~300 EUR pour 5 min et ~3 600 EUR pour 1 h.
**Enseignement pour l'arbitrage** : le coût direct est faible devant les coûts indirects et réglementaires, et ceux-ci croissent par **seuils de durée** (cf. `docs/nis2-dora.md`, classification d'incident majeur). Passer d'une reprise manuelle (« minutes à heures », sujet §1) à une reprise automatique bornée (cible < 1 min, `docs/pca-pra.md`) change la **classe** de l'incident, pas seulement son coût.

### 1.4 Biens supports (BS)

| Id | Bien support | Exposition / privilèges | Valeurs portées | Réf. |
|---|---|---|---|---|
| **BS1** | **WAF** Nginx + ModSecurity + CRS | **Seul** point d'entrée HTTP (80/443, TLS auto-signé ; + `127.0.0.1:9443` réservé à l'hôte pour le back-office, annexe A) ; porte la deny-list IP | VM1, VM4 | `security/waf/` [R] (conf), déploiement via `infra/compose` [R] |
| **BS2** | **front** (React, Nginx) | derrière le WAF ; en-têtes de sécurité | VM1 | `services/front/` [R] |
| **BS3** | **payment-api** (FastAPI) | réseau `app` ; valide le JWT localement (HS256 épinglé, `exp`/`sub` requis) | VM1, VM2 | `services/payment-api/` [R] |
| **BS4** | **auth** (FastAPI) | réseau `app` ; bcrypt, rate-limit `10/minute` par IP (stockage mémoire), API interne `/internal/tighten-rate-limit` | VM4, VM1 | `services/auth/` [R] |
| **BS5** | **Postgres 16** + dumps | réseau `data` `internal: true`, jamais exposé | VM2, VM1 | `libs/python/resilience_db` [R] ; playbook `pg_backup.yml` [R] ; dumps planifiés [S] (planification à activer) |
| **BS6** | **Moteur de remédiation** | **privilèges élevés par nature** ; API authentifiée (token), hors réseau `edge`, accès Docker via `docker-socket-proxy` (liste blanche stricte de 5 couples méthode/chemin : inspection, restart, reload à chaud du WAF), playbooks Ansible nommés | VM3, (VM1, VM2 en cas d'abus) | `remediation/` [R] ; proxy et compose [R] |
| **BS7** | **Chaîne d'observabilité et de détection** : Prometheus, Loki, Promtail, collector, detector (IsolationForest v1.0.0), Alertmanager | réseau `obs`/`app` | VM3 | `ml/*` [R] ; `infra/*` [R] |
| **BS8** | **Secrets** SOPS + age | clé privée age **hors git** | VM4 | `security/sops/` [R] (règles ; `.sops.yaml` contient encore une clé publique d'exemple, `secrets.enc.env` à créer) |
| **BS9** | **Hôte** (PC `192.168.137.1`, Docker Desktop, hotspot `RESILIENCE-G1`) | point unique de déploiement | tous | `CAHIER-DES-CHARGES.md` §4 |
| **BS10** | **Assistant RAG** (Ollama) | non privilégié, séparé de l'automate (sujet §3.3) | aucune valeur critique | `assistant/` [R] |

### 1.5 Socle de sécurité : mesures en place et écarts assumés

En place : réseaux `edge`/`app`/`data`/`obs` avec `data` interne [R compose] ; conteneurs non-root, `cap_drop: ALL`, `read_only`, limites ([R] dans `infra/compose`, `security/hardening/hardening.md` + `audit.sh` [R]) ; logs JSON normalisés avec `request_id` ; JWT à `alg` épinglé ; mots de passe hachés ; validation stricte des paramètres d'actions.
**Écarts connus** (à lire comme risques résiduels, cf. atelier 5) : pas de MFA sur le parcours client (le **back-office** est renforcé par visage + mot de passe, annexe A) ; secret JWT **symétrique partagé** entre `auth` et `payment-api` ; rate-limit en mémoire (perdu au redémarrage) ; TLS auto-signé ; pas de sauvegarde hors hôte ; un seul hôte, un seul WAF, un seul Postgres.

---

## Atelier 2 — Sources de risque et objectifs visés

| Id | Source de risque (SR) | Objectif visé (OV) | Motivation / ressources | Pertinence |
|---|---|---|---|---|
| **SR1** | Attaquant externe opportuniste (hacktiviste, extorsion) | Rendre le paiement indisponible, nuire à l'image | moyenne / faibles (outils de flood publics) | **Retenue** |
| **SR2** | Cybercriminel orienté fraude | Prendre des comptes, détourner des fonds ; exploiter une faille web | forte / moyennes | **Retenue** |
| **SR3** | Attaquant ciblé (concurrent, acteur persistant) | Altérer ou exfiltrer des données financières, saper la confiance | moyenne / élevées | **Retenue** (accès initial supposé) |
| **SR4** | Initié négligent ou malveillant (exploitation, dev) | Fuite de secret, mauvaise manipulation | variable / accès légitime | **Retenue** pour la gestion des secrets |
| (SR0) | Banc d'essai interne (PC Attaquant, `attacks/`) | Représente SR1-SR3 **de façon bornée et contrôlée** | n/a | Outil d'essai, pas une menace |

Hors périmètre retenu : acteur étatique, attaque physique sur l'hôte, déni de service volumétrique réseau (hors du hotspot ; **risque transféré** à un fournisseur de scrubbing en contexte réel).

---

## Atelier 3 — Scénarios stratégiques

Chemins d'attaque vers les valeurs métier, via l'écosystème. Parties prenantes pertinentes : **hôte/réseau hotspot** (le PC Attaquant est sur le même réseau que l'hôte), **chaîne d'approvisionnement logicielle** (images Docker, paquets pip/npm, modèle LLM local, voir aussi `docs/nis2-dora.md`), **utilisateurs**.

| Id | Source -> objectif | Chemin d'attaque (haut niveau) | Événement redouté | Valeurs |
|---|---|---|---|---|
| **SS1** | SR1 -> indisponibilité | Flood HTTPS sur le WAF puis `payment-api` jusqu'à saturation CPU/DB | **ER1 Indisponibilité du paiement** | VM1, VM3 |
| **SS2** | SR2 -> fraude | Credential stuffing sur `/api/v1/login` -> session valide -> virements frauduleux | **ER4 Abus d'authentification** | VM4, VM2 |
| **SS3** | SR2/SR3 -> accès aux données | Injection / traversée de chemin via front ou API (`/api/v1/*`) | ER2 (et ER3 si lecture de secrets) | VM2, VM4 |
| **SS4** | SR3 -> altération | Accès applicatif ou DB acquis, puis modification de comptes/soldes | **ER2 Altération de données** | VM2 |
| **SS5** | SR4 / supply chain -> secret | Secret en clair dans le dépôt/l'archive, clé age exposée, image piégée | **ER3 Compromission de secret** | VM4 |
| **SS6** | SR2/SR3 -> automate | Vol du `REMEDIATION_TOKEN`, ou détournement du moteur pour agir sur Docker/WAF (y compris via un proxy qui détiendrait le jeton : nginx du dashboard) | **ER5 Abus du moteur de remédiation** | VM3, VM1 |

### Événements redoutés (ER), gravité **sans** traitement

| Id | Événement redouté | Gravité | Justification |
|---|---|---|---|
| **ER1** | Indisponibilité du service de paiement | **G3** | reprise historiquement manuelle donc > 5 min (sujet §1) |
| **ER2** | Altération de données (soldes, transactions) | **G4** | perte financière non bornée, confiance, preuve compromise |
| **ER3** | Compromission d'un secret (`JWT_SECRET`, `POSTGRES_PASSWORD`, tokens) | **G4** | `JWT_SECRET` permet de forger un jeton pour n'importe quel compte |
| **ER4** | Abus d'authentification (prise de compte, saturation de `/login`) | **G3** | fraude individuelle ou déni de connexion |
| **ER5** | Abus du moteur de remédiation (privilèges élevés) | **G4** | un accès brut au socket Docker serait équivalent à root sur l'hôte |

---

## Atelier 4 — Scénarios opérationnels (= scénarios réellement implémentés)

Correspondance **1 pour 1** avec `attacks/scenarios/*.yml`, validée par `attacks/validate_scenarios.py` et `attacks/tests/test_scenarios.py` (4 tests verts au 2026-10-19). Chaque ligne relie l'attaque à la **détection** (features du vecteur ML, `docs/contracts.md` §2), à l'`incident_type` (§3) et à l'**action** de `remediation/decision_table.yml` (§4).

| Id | Scénario (`attacks/`) | Mode opératoire (ATT&CK) | Paramètres plafonnés | Signal observable (métrique / Loki) | Feature ML dominante | `incident_type` -> actions | Critère de réussite |
|---|---|---|---|---|---|---|---|
| **SO1** | `service_flood` | Saturation applicative (T1499.002) : rafale `POST /api/v1/transactions` | <= 80 req/s, 30 s (`run.sh` plafonne à 100/s, 60 s) | `rate(resilience_http_requests_total{service="payment-api"})`, 5xx, p95 ; `db_error` | `req_per_s`, `ratio_5xx`, `p95_latency_ms` | `service_flood` -> `waf_block_ip` + `restart_service(payment-api)` | `verify_tx` OK sans intervention humaine |
| **SO2** | `auth_abuse` | Credential stuffing / force brute (T1110.004) sur `/api/v1/login` | <= 40 tent./s, 30 s | `resilience_auth_logins_total{result="failed"}`, `resilience_auth_rate_limited_total` ; `auth_login_failed` | `auth_failed_per_s` | `auth_abuse` -> `waf_block_ip` + `tighten_rate_limit(auth, x0.5)` | `verify_tx` OK ; logins légitimes toujours possibles |
| **SO3** | `web_attack` | Exploitation d'application exposée (T1190) : charges CRS de test (`' OR '1'='1`, `../../etc/passwd`) | <= 20 req/s, 20 s | `resilience_waf_blocked_total{rule}` ; `waf_blocked` | `waf_blocked_per_s` | `web_attack` -> `confirm_waf_block` + `waf_blacklist_ip` | 403 sur les requêtes malveillantes, source en liste noire, `verify_tx` OK |
| **SO4** | `data_corruption` | Manipulation de données stockées (T1565.001), altération contrôlée et réversible de données fictives | altération bornée aux données fictives | `resilience_db_errors_total` ; `db_error` ; `verify_tx` KO | `db_errors_per_s` | `data_corruption` -> `restore_pg_dump(latest)` **seul** | données cohérentes restaurées, `verify_tx` OK |
| SO5 | (pas de scénario rejoué) | Secret exposé (T1552) / compte valide (T1078) | n/a | n/a | n/a | **mesures préventives** (SOPS, gitleaks, `audit.sh`) | `audit.sh` conforme, aucun secret dans l'archive |
| SO6 | (pas de scénario rejoué) | Abus du moteur (token volé, appel Docker/Ansible hors périmètre) | n/a | `remediation_action` anormale | n/a | **mesures préventives** (voir 5.2) | refus des appels hors liste blanche (tests dans `remediation/tests/` [R]) |

**Point de conception à défendre (sujet §2, §3.4)** : SO1 et SO4 reçoivent des réponses **volontairement différentes**. La disponibilité se rétablit en coupant la source et en redémarrant (état conservé) ; la corruption exige de **restaurer** un état sain. Ce n'est pas qu'une convention : `remediation/decision.py` **refuse de charger la table** (fail closed) si `data_corruption` contient `restart/recreate`, ou si `restore_pg_dump` apparaît dans une autre règle, ou si la règle `unknown` contient une action destructive. Ces invariants sont dans le code ; leurs tests unitaires sont livrés dans `remediation/tests/` (`test_decision_table.py`, `test_engine.py`, `test_actions.py`…) [R].

**Qualité de la détection (honnêteté)** : modèle IsolationForest v1.0.0, seuil 0,6296 (quantile 99,9 % de la baseline). Sur le jeu d'évaluation : 0/2000 faux positifs sur trafic normal ; détection modèle seul : `service_flood` 100 %, `auth_abuse` 98,6 %, `web_attack` 95,7 %, `data_corruption` 100 % ; 100 % avec le garde-fou statistique (z >= 12,97). **Limite** : baseline et attaques sont **synthétiques** (`ml/training/dataset.py`), pas du trafic réel ; le type d'incident est étiqueté par une heuristique de routage (`classify_incident`), pas par le modèle (limite assumée, `docs/contracts.md` §3).

---

## Cotation des risques

| Id | Risque | Gravité init. | Vraisemblance init. | **Niveau initial** | Gravité rés. | Vraisemblance rés. | **Niveau résiduel** |
|---|---|---|---|---|---|---|---|
| SO1 | Indisponibilité par flood (ER1) | 3 | 4 | **12 Élevé** | 2 | 3 | **6 Moyen** |
| SO2 | Abus d'authentification (ER4) | 3 | 4 | **12 Élevé** | 3 | 2 | **6 Moyen** |
| SO3 | Attaque web / injection (ER2, ER3) | 4 | 3 | **12 Élevé** | 4 | 2 | **8 Moyen** |
| SO4 | Corruption de données (ER2) | 4 | 2 | **8 Moyen** | 3 | 2 | **6 Moyen** |
| SO5 | Compromission de secret (ER3) | 4 | 3 | **12 Élevé** | 4 | 2 | **8 Moyen** |
| SO6 | Abus du moteur de remédiation (ER5) | 4 | 3 | **12 Élevé** | 3 | 1 | **3 Faible** |

Justification des **baisses** (elles doivent venir d'une mesure, pas d'un voeu) :
- SO1 : la gravité passe de 3 à 2 parce que l'indisponibilité est bornée par le MTTR automatique (cible < 1 min, `docs/pca-pra.md`) ; la vraisemblance ne tombe que de 4 à 3 : un attaquant qui change d'IP ou un flood distribué contourne le blocage de source.
- SO2 : vraisemblance 4 -> 2 grâce au rate-limit par IP, au blocage WAF et au durcissement x0,5 ; la gravité reste 3 (pas de MFA, pas de verrouillage par compte).
- SO3 : vraisemblance 3 -> 2 (CRS + ORM paramétré + validation Pydantic) ; la gravité reste 4 : un contournement CRS ou un 0-day garde un impact critique.
- SO4 : la gravité passe de 4 à 3 parce que la perte est **bornée au RPO** (dump) et la correction vérifiée ; elle n'est pas nulle.
- SO5 : vraisemblance 3 -> 2 (SOPS, `*_FILE`, gitleaks, `audit.sh`) ; la gravité reste 4 tant que le secret JWT est symétrique et partagé.
- SO6 : sans traitement (socket Docker brut), G4 x V3 ; avec proxy à verbes limités, liste blanche et token, l'abus se réduit à des redémarrages de 3 services : G3 x V1.

### Matrice gravité x vraisemblance

Avant traitement :

| Gravité \ Vraisemblance | V1 Minime | V2 Possible | V3 Vraisemblable | V4 Quasi certaine |
|---|---|---|---|---|
| **G4 Critique** | | SO4 | **SO3, SO5, SO6** | |
| **G3 Grave** | | | | **SO1, SO2** |
| **G2 Significative** | | | | |
| **G1 Mineure** | | | | |

Après traitement (résiduel) :

| Gravité \ Vraisemblance | V1 Minime | V2 Possible | V3 Vraisemblable | V4 Quasi certaine |
|---|---|---|---|---|
| **G4 Critique** | | SO3, SO5 | | |
| **G3 Grave** | SO6 | SO2, SO4 | | |
| **G2 Significative** | | | SO1 | |
| **G1 Mineure** | | | | |

Aucun risque Élevé ou Critique ne subsiste. Les quatre risques Moyens (SO1-SO5) sont **proposés à l'acceptation de la direction** sous conditions (section suivante et `docs/pca-pra.md` §8).

---

## Atelier 5 — Traitement du risque

### 5.1 Mesures par risque (composant, type, preuve vérifiable)

| Risque | Mesure | Type | Composant / preuve | Statut |
|---|---|---|---|---|
| SO1 | **Détection ML** du pic multi-signaux (score >= 0,6296 ou garde-fou z >= 12,97) puis événement `POST /events` | Détective | `ml/detector/core.py`, `ml/training/artifacts/v1.0.0/` (hash `sha256` vérifié au chargement) | [R] |
| SO1 | **Blocage de la source** (deny-list WAF, `never_block_ips` protège l'hôte) puis **redémarrage** de `payment-api` via proxy (liste blanche `payment-api`, `auth`, `front`) | Correctif | `remediation/actions/waf.py`, `docker.py`, `docker_proxy.py` | [R] code, playbook `waf_deny_ip.yml` et proxy |
| SO1, SO2, SO3 | **WAF** CRS : filtrage applicatif, seul point exposé, log JSON, métrique `resilience_waf_blocked_total` | Préventif, détectif | `security/waf/nginx.conf`, `waf_exporter.py` (25 tests verts) | [R] conf et déploiement compose |
| SO2 | **Rate-limit** `/login` 10/min par IP, resserrable à chaud (x0,5, plancher 1/min). Le moteur envoie une `Idempotency-Key` = incident, mais **`auth` ne la dédoublonne pas encore** : une nouvelle tentative du moteur re-multiplie la limite (10 -> 5 -> 2 -> 1/min) | Préventif, correctif | `services/auth/.../ratelimit.py`, `remediation/actions/rate_limit.py` | [R] ; dédoublonnage [S], écart à corriger |
| SO2 | Hachage des mots de passe, JWT 15 min à `alg` épinglé | Préventif | `services/auth`, `payment_api/security.py` | [R] |
| SO3 | Validation d'entrée, ORM paramétré, `confirm_waf_block` (lecture Loki) puis blacklist permanente | Préventif, correctif | `payment_api/schemas.py`, `remediation/actions/waf.py` | [R] |
| SO4 | **Restauration** du dernier dump (`restore_pg_dump`, playbook `pg_restore.yml`), contrainte `balance_cents >= 0`, transferts atomiques, vérification `verify_tx` | Correctif | `remediation/actions/postgres.py`, `resilience_db/models.py`, `ledger.py` | [R] code et playbook `pg_restore.yml` ; playbook `pg_backup.yml` [R] ; **planification périodique du dump [S]** |
| SO5 | **SOPS + age**, clé privée hors git, `*_FILE` pour les secrets du moteur, `gitleaks` pre-commit, `audit.sh` avant packaging | Préventif | `security/sops/`, `remediation/config.py`, `security/hardening/audit.sh` | [R] ; clé age réelle et `secrets.enc.env` [S] |
| SO6 | **docker-socket-proxy** (liste blanche 5 couples : inspection + restart + reload WAF) **+ liste blanche côté client** (méthode+chemin) ; playbooks **nommés** uniquement (`ALLOWED_PLAYBOOKS`) ; API par token (>= 16 car.) ; **écritures humaines (déblocage d'IP) soumises à un jeton opérateur distinct** (`REMEDIATION_OPERATOR_TOKEN`, jamais injecté par le nginx du dashboard, qui ne détient que le jeton de service des lectures — `test_dashboard_proxy.py`, `test_unblock.py`) ; hors `edge` ; `never_block_ips` ; `dry_run` forçable ; cooldown/`max_attempts` ; actions sérialisées | Préventif | `remediation/actions/docker_proxy.py`, `runner.py`, `config.py`, `engine.py` | [R] code, proxy et isolation réseau (compose) |
| Tous | **Durcissement** conteneurs (non-root, `cap_drop: ALL`, `read_only`, `no-new-privileges`, limites, healthchecks) | Préventif | `security/hardening/hardening.md`, `audit.sh` | [R] doc+audit ; application compose [R] |
| Tous | **Fonction SOC** : règles Loki/Grafana sur les `event` normalisés (`auth_login_failed`, `waf_blocked`, `db_error`...), journal d'incident et timeline | Détective | `docs/contracts.md` §1, `remediation/journal.py`, `timeline.py` | journal [R] ; règles SOC (`infra/prometheus/rules/soc.yml`, `infra/grafana/provisioning/alerting/soc-rules.yml`) [R] |

### 5.2 Décision de traitement

| Risque | Décision | Condition / indicateur de surveillance |
|---|---|---|
| SO1 | **Réduire** (auto) ; DDoS volumétrique distribué : **transférer** (scrubbing opérateur) | MTTR `resilience_mttr_seconds` <= RTO ; nb d'escalades `remediation_failed` |
| SO2 | **Réduire** ; MFA et verrouillage par compte : **à planifier** (hors 4 jours) | `resilience_auth_logins_total{result="failed"}` ; alertes `auth_login_failed` |
| SO3 | **Réduire** ; surveiller les contournements CRS | `resilience_waf_blocked_total{rule}` ; tests de payloads |
| SO4 | **Réduire** et **accepter la perte bornée au RPO** | âge du dernier dump <= RPO ; test de restauration périodique |
| SO5 | **Réduire** ; passer à Vault/HSM et JWT asymétrique en contexte réel | `audit.sh` conforme ; 0 résultat `gitleaks` |
| SO6 | **Réduire** ; rester sur proxy restreint (**ne jamais** monter le socket brut) | `audit.sh` §1-2 ; revue de `ALLOWED_PLAYBOOKS` et `restartable_services` |

### 5.3 Risques résiduels majeurs à porter devant la direction

1. **Détection calibrée sur données synthétiques** : les taux (0 faux positif, >= 95 % de détection) ne se transposent pas tels quels à du trafic réel ; un faux positif déclenche un redémarrage inutile de `payment-api`.
2. **Corruption silencieuse** (sans `db_error`) non détectée par le signal retenu ; et un dump déjà corrompu serait restauré par `latest` (voir `docs/pca-pra.md` §8).
3. **Pas de retour arrière automatique** des mesures (deny-list sans expiration implémentée côté moteur, rate-limit durci levé seulement au redémarrage de `auth`, et re-durci à chaque nouvelle tentative faute de dédoublonnage) : un faux positif ou plusieurs tentatives peuvent pénaliser des utilisateurs légitimes (jusqu'au plancher de 1 tentative/min).
4. **Moteur de remédiation** : c'est à la fois la meilleure défense et la cible de plus forte valeur ; son périmètre de privilèges est **spécifié et testé en code**, et l'isolation réseau et la configuration du proxy sont désormais câblées dans `infra/compose` [R] ; leur preuve d'exécution reste à établir en recette [M].
5. **Passerelle Alertmanager -> remédiation non authentifiée** (P4S-01) : en profil `full`, l'API Alertmanager (`:9093`) n'a pas d'auth propre et est joignable depuis le réseau `app` ; un conteneur `app` compromis pourrait forger une alerte relayée au moteur avec le Bearer. Durcissement cible : réseau `soc` dédié (`internal`) partagé uniquement par `prometheus`, `alertmanager` et `remediation`. Impact borné par la liste blanche d'actions et la validation des paramètres.
6. **Chiffrement en transit limité** (P4S-07) : le WAF termine en TLS auto-signé mais sert aussi l'applicatif en HTTP clair sur `:80` sans redirection ni HSTS ; les identifiants transitent en clair si le client utilise `http://`. Trafic confiné au hotspot du projet ; cible : redirection 301 vers HTTPS + HSTS.
7. **Journal d'audit WAF** (P4S-03) : le journal ModSecurity (`RelevantOnly`, volume interne `waf-logs`) peut contenir les en-têtes/corps des requêtes **bloquées** ; un login légitime n'étant pas bloqué, le risque de journaliser un mot de passe réel est faible. Cible : rotation/plafond de taille du volume.

### 5.4 Plan d'action priorisé (sprint)

| Priorité | Action | Pilier | Échéance |
|---|---|---|---|
| P1 | `infra/compose` (réseaux, durcissement) livré [R] ; lancer `audit.sh` dessus | Infra / Cyber | J2 |
| P1 | Playbooks `waf_deny_ip.yml`, `pg_restore.yml`, `pg_backup.yml` livrés [R] ; reste la **planification périodique du dump** (condition du RPO) [S] | Infra | J3 |
| P1 | `scripts/verify_tx` livré [R] ; rejeu des 4 scénarios et relevé des MTTR [M] | Dév / Infra | J3-J4 |
| P2 | Clé age réelle + `secrets.enc.env` ; relecture `gitleaks` | Cyber | J2 |
| P2 | Règles SOC sur les `event` normalisés : livrées [R] (`soc.yml`, `soc-rules.yml`) | Cyber / Infra | J3 |
| P3 | Mettre à jour cette cotation avec les MTTR mesurés et les incidents du chaos engineering | Transformation | J4 |

---

## Annexe — Consigne Additionnelle 1 : accès privilégié du back-office (visage + LED)

> Ajout du 2026-10-20 (intégration de bout en bout). Cadrage : `docs/consigne-additionnelle-1.md` ; décisions : `docs/adr/0007-acces-hote-vivacite-poses-photos-chiffrees.md` ; interfaces : `docs/contracts.md` §5. Cotations **proposées**, à valider par la direction ; mesures marquées **[R]** = présentes dans le dépôt et testées hors stack, **[M]** = à valider en **recette** (caméra réelle, build Docker de dlib, ESP8266, broker live : **non faite à ce jour**).

### A.1 Valeur métier et biens supports ajoutés

| Id | Élément | Critère dominant | Où |
|---|---|---|---|
| **VM5** | **Accès privilégié au back-office** (habilitations, rôles, visages des agents) | Confidentialité, intégrité | `services/backoffice`, `services/auth` (`/api/v1/admin/*`) |
| **BS11** | **face-id** (modèle `face_recognition`/dlib de l'équipe) + table `face_enrollments` | Confidentialité (donnée biométrique **sensible, RGPD**) | `services/face-id`, `resilience_db` migrations `0002`/`0009` [R] |
| **BS12** | **Clé `FACE_DATA_KEY`** (AES-256-GCM, SOPS) | Confidentialité | `security/sops/secrets.example.env` [R] ; clé réelle [S] |
| **BS13** | **Broker MQTT + ESP8266 + LED** | Disponibilité (témoin), pas un facteur | `infra/mosquitto`, `iot/esp8266-led` [R] code, [M] matériel |
| **BS14** | **Listener hôte WAF `127.0.0.1:9443`** | Intégrité du périmètre | `security/waf/nginx.conf`, `infra/compose` [R] |

BS1 est précisé : le WAF publie 80/443 **et** 9443 en **loopback uniquement** (hôte) ; `/api/v1/auth/*` et `/api/v1/admin/*` ne sont **pas** servis sur 80/443 (404). Le broker MQTT est le **seul** autre port publié (interface hotspot).

### A.2 Scénarios et risques

| Id | Scénario (source -> chemin) | Événement redouté | Mesures (preuve) |
|---|---|---|---|
| **SO7** | **Usurpation du visage** (SR2/SR3) : photo ou vidéo d'un agent présentée à la caméra, puis mot de passe volé | **ER6 Prise de compte privilégié** | **Vivacité par poses** : 3 poses dans un **ordre aléatoire tiré par le serveur** à chaque `identify`, chaque frame validée en pose **et** identité (écarte la photo statique unique et la vidéo à ordre fixe, **pas** 3 poses rejouées dans l'ordre affiché) ; le visage n'est **pas** un bypass (mot de passe + rôle requis) ; verrouillage 2 échecs -> 5 min par `(username, ip)` ; refroidissement 30 s [R tests auth/face-id] ; seuils de pose et d'identité à calibrer [M] |
| **SO8** | **Fuite biométrique** (SR3/SR4) : lecture de la base et/ou de la clé | **ER7 Fuite de données biométriques (RGPD)** | Gabarits **et** vignettes (240 px max) **chiffrés AES-256-GCM**, AAD = username, clé SOPS hors base ; liste sans biométrie ; consultation admin **journalisée** (`face_photos_viewed`) ; aucun log d'image/embedding ; effacement total (`DELETE`) [R] ; **amendement de la règle « jamais d'image » à valider par l'équipe (Yanis)** |
| **SO9** | **Indisponibilité du facteur visage** (panne face-id, perte de clé, caméra HS) : auto-DoS de l'accès privilégié | **ER8 Back-office inaccessible** | Inaccessible **par conception** ; boucle ZTR, `verify_tx` et front **indépendants** (D4) ; **break-glass** et réenrôlement : `docs/pca-pra.md` §5.7 ; garde-fou `last_admin` [R] ; bootstrap par token [R] |
| **SO10** | **Abus des surfaces ajoutées** (SR1/SR2) : poste du hotspot -> broker MQTT ; accès à l'API d'administration depuis le réseau | ER4 (étendu) | Broker `allow_anonymous false`, ACL par topic (`auth` écrit `cmd`, lit `status` ; `led` l'inverse), bind hotspot, conteneur durci ; MQTT **fail-open** (la LED n'est qu'un témoin) ; admin API **absente du serveur public**, rôle `admin` revalidé en base, bootstrap temps constant + rate-limit [R] ; broker et ESP réels [M] |

### A.3 Cotation (proposée)

| Id | Risque | G init. | V init. | **Initial** | G rés. | V rés. | **Résiduel** |
|---|---|---|---|---|---|---|---|
| SO7 | Usurpation de visage (ER6) | 3 | 3 | **9 Élevé** | 3 | 2 | **6 Moyen** |
| SO8 | Fuite biométrique (ER7) | 4 | 3 | **12 Élevé** | 4 | 2 | **8 Moyen** |
| SO9 | Back-office inaccessible (ER8) | 2 | 3 | **6 Moyen** | 2 | 2 | **4 Faible** |
| SO10 | Abus de la surface MQTT / admin | 2 | 3 | **6 Moyen** | 1 | 2 | **2 Faible** |

Justifications : SO7 passe de V3 à V2 grâce à la vivacité par poses (photo statique unique et vidéo à ordre fixe écartées), au listener loopback (caméra de l'hôte) et au second facteur obligatoire ; reste un résiduel pour **3 poses rejouées / photos présentées dans l'ordre affiché** (l'ordre est annoncé au client, les frames portent leur label de pose), pour un **deepfake temps réel**, chacun **avec** le mot de passe. SO8 reste G4 (donnée sensible, non révocable) : seule la vraisemblance baisse, car il faut **base et clé** ; un accès root à l'hôte donne les deux (hors périmètre retenu, BS9). SO9 : gravité bornée à G2 car la **disponibilité du paiement** (VM1) et la reprise autonome (VM3) n'en dépendent pas.

### A.4 Risques résiduels à porter devant la direction (ajouts)

8. **Photos d'agents conservées (chiffrées)** : écart assumé avec la règle « embedding seul ». Base légale, durée de conservation et **validation par l'équipe (Yanis)** à acter avant tout usage réel.
9. **Vivacité contournable** : 3 poses rejouées (photos imprimées ou trames capturées, présentées/soumises dans l'ordre affiché) et deepfake temps réel ne sont pas couverts ; pas de détection de profondeur. Pistes : entropie du challenge (poses haut/bas, séquences de 4–5 étapes), contraintes temporelles côté serveur, détection de clignement (EAR) / micro-mouvements.
10. **Non-recette** : modèle réel (dlib), caméra, ESP physique, broker live et **calibrage des marges de capture** (client 0,07 / 0,22 vs serveur 0,10 / 0,15) n'ont pas été validés sur le PC Hôte ; les taux de faux rejet / fausse acceptation sont **inconnus** (aucune mesure).
11. **Store de challenge, refroidissement et verrouillage en mémoire** (perdus au redémarrage de `auth`, un seul worker) : limite héritée, voir `docs/consigne-additionnelle-1.md` §10.
