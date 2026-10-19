# Analyse de risques EBIOS Risk Manager — RESILIENCE-ALPHA

> Couvre **R16**. Version **v1 (J1, 2026-10-19)**, à réviser après la recette (J3/J4) avec les MTTR mesurés.
> Périmètre : plateforme de paiement **fictive** d'une entité financière fictive, telle que décrite dans `CAHIER-DES-CHARGES.md` §4 et `docs/contracts.md`. Aucune donnée réelle.

**Légende de statut des mesures (honnêteté de preuve)** : **[R]** réalisé et présent dans le dépôt au 2026-10-19 · **[S]** spécifié (contrat / CDC) mais composant pas encore livré · **[M]** valeur à mesurer en recette.
État du dépôt au 2026-10-19 : `services/*`, `ml/*`, `remediation/*`, `security/*`, `attacks/*` existent ; `infra/compose`, `infra/ansible/playbooks`, `infra/{prometheus,loki,grafana,alertmanager}`, `dashboard/`, `scripts/verify_tx` sont encore vides ou absents.

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
| **BS1** | **WAF** Nginx + ModSecurity + CRS | **Seul** composant exposé (80/443, TLS auto-signé) ; porte la deny-list IP | VM1, VM4 | `security/waf/` [R] (conf), déploiement [S] |
| **BS2** | **front** (React, Nginx) | derrière le WAF ; en-têtes de sécurité | VM1 | `services/front/` [R] |
| **BS3** | **payment-api** (FastAPI) | réseau `app` ; valide le JWT localement (HS256 épinglé, `exp`/`sub` requis) | VM1, VM2 | `services/payment-api/` [R] |
| **BS4** | **auth** (FastAPI) | réseau `app` ; bcrypt, rate-limit `10/minute` par IP (stockage mémoire), API interne `/internal/tighten-rate-limit` | VM4, VM1 | `services/auth/` [R] |
| **BS5** | **Postgres 16** + dumps | réseau `data` `internal: true`, jamais exposé | VM2, VM1 | `libs/python/resilience_db` [R] ; dumps planifiés [S] |
| **BS6** | **Moteur de remédiation** | **privilèges élevés par nature** ; API authentifiée (token), hors réseau `edge`, accès Docker via `docker-socket-proxy` (restart seul), playbooks Ansible nommés | VM3, (VM1, VM2 en cas d'abus) | `remediation/` [R] ; proxy et compose [S] |
| **BS7** | **Chaîne d'observabilité et de détection** : Prometheus, Loki, Promtail, collector, detector (IsolationForest v1.0.0), Alertmanager | réseau `obs`/`app` | VM3 | `ml/*` [R] ; `infra/*` [S] |
| **BS8** | **Secrets** SOPS + age | clé privée age **hors git** | VM4 | `security/sops/` [R] (règles ; `.sops.yaml` contient encore une clé publique d'exemple, `secrets.enc.env` à créer) |
| **BS9** | **Hôte** (PC `192.168.137.1`, Docker Desktop, hotspot `RESILIENCE-G1`) | point unique de déploiement | tous | `CAHIER-DES-CHARGES.md` §4 |
| **BS10** | **Assistant RAG** (Ollama) | non privilégié, séparé de l'automate (sujet §3.3) | aucune valeur critique | `assistant/` [R] |

### 1.5 Socle de sécurité : mesures en place et écarts assumés

En place : réseaux `edge`/`app`/`data`/`obs` avec `data` interne [S compose] ; conteneurs non-root, `cap_drop: ALL`, `read_only`, limites ([S], `security/hardening/hardening.md` + `audit.sh` [R]) ; logs JSON normalisés avec `request_id` ; JWT à `alg` épinglé ; mots de passe hachés ; validation stricte des paramètres d'actions.
**Écarts connus** (à lire comme risques résiduels, cf. atelier 5) : pas de MFA ; secret JWT **symétrique partagé** entre `auth` et `payment-api` ; rate-limit en mémoire (perdu au redémarrage) ; TLS auto-signé ; pas de sauvegarde hors hôte ; un seul hôte, un seul WAF, un seul Postgres.

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
| **SS6** | SR2/SR3 -> automate | Vol du `REMEDIATION_TOKEN`, ou détournement du moteur pour agir sur Docker/WAF | **ER5 Abus du moteur de remédiation** | VM3, VM1 |

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
| SO6 | (pas de scénario rejoué) | Abus du moteur (token volé, appel Docker/Ansible hors périmètre) | n/a | `remediation_action` anormale | n/a | **mesures préventives** (voir 5.2) | refus des appels hors liste blanche (tests à écrire [S]) |

**Point de conception à défendre (sujet §2, §3.4)** : SO1 et SO4 reçoivent des réponses **volontairement différentes**. La disponibilité se rétablit en coupant la source et en redémarrant (état conservé) ; la corruption exige de **restaurer** un état sain. Ce n'est pas qu'une convention : `remediation/decision.py` **refuse de charger la table** (fail closed) si `data_corruption` contient `restart/recreate`, ou si `restore_pg_dump` apparaît dans une autre règle, ou si la règle `unknown` contient une action destructive. Ces invariants sont dans le code ; leurs tests unitaires (`remediation/tests/`, vide au 2026-10-19) sont à écrire [S].

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
| SO1 | **Blocage de la source** (deny-list WAF, `never_block_ips` protège l'hôte) puis **redémarrage** de `payment-api` via proxy (liste blanche `payment-api`, `auth`, `front`) | Correctif | `remediation/actions/waf.py`, `docker.py`, `docker_proxy.py` | [R] code ; playbook `waf_deny_ip.yml` et proxy [S] |
| SO1, SO2, SO3 | **WAF** CRS : filtrage applicatif, seul point exposé, log JSON, métrique `resilience_waf_blocked_total` | Préventif, détectif | `security/waf/nginx.conf`, `waf_exporter.py` (5 tests verts) | [R] conf ; déploiement [S] |
| SO2 | **Rate-limit** `/login` 10/min par IP, resserrable à chaud (x0,5, plancher 1/min). Le moteur envoie une `Idempotency-Key` = incident, mais **`auth` ne la dédoublonne pas encore** : une nouvelle tentative du moteur re-multiplie la limite (10 -> 5 -> 2 -> 1/min) | Préventif, correctif | `services/auth/.../ratelimit.py`, `remediation/actions/rate_limit.py` | [R] ; dédoublonnage [S], écart à corriger |
| SO2 | Hachage des mots de passe, JWT 15 min à `alg` épinglé | Préventif | `services/auth`, `payment_api/security.py` | [R] |
| SO3 | Validation d'entrée, ORM paramétré, `confirm_waf_block` (lecture Loki) puis blacklist permanente | Préventif, correctif | `payment_api/schemas.py`, `remediation/actions/waf.py` | [R] |
| SO4 | **Restauration** du dernier dump (`restore_pg_dump`, playbook `pg_restore.yml`), contrainte `balance_cents >= 0`, transferts atomiques, vérification `verify_tx` | Correctif | `remediation/actions/postgres.py`, `resilience_db/models.py`, `ledger.py` | [R] code ; **dump planifié et playbook [S]** |
| SO5 | **SOPS + age**, clé privée hors git, `*_FILE` pour les secrets du moteur, `gitleaks` pre-commit, `audit.sh` avant packaging | Préventif | `security/sops/`, `remediation/config.py`, `security/hardening/audit.sh` | [R] ; clé age réelle et `secrets.enc.env` [S] |
| SO6 | **docker-socket-proxy** (restart seul) **+ liste blanche côté client** (méthode+chemin) ; playbooks **nommés** uniquement (`ALLOWED_PLAYBOOKS`) ; API par token (>= 16 car.) ; hors `edge` ; `never_block_ips` ; `dry_run` forçable ; cooldown/`max_attempts` ; actions sérialisées | Préventif | `remediation/actions/docker_proxy.py`, `runner.py`, `config.py`, `engine.py` | [R] code ; proxy et isolation réseau [S] |
| Tous | **Durcissement** conteneurs (non-root, `cap_drop: ALL`, `read_only`, `no-new-privileges`, limites, healthchecks) | Préventif | `security/hardening/hardening.md`, `audit.sh` | [R] doc+audit ; application compose [S] |
| Tous | **Fonction SOC** : règles Loki/Grafana sur les `event` normalisés (`auth_login_failed`, `waf_blocked`, `db_error`...), journal d'incident et timeline | Détective | `docs/contracts.md` §1, `remediation/journal.py`, `timeline.py` | journal [R] ; règles Loki [S] |

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
4. **Moteur de remédiation** : c'est à la fois la meilleure défense et la cible de plus forte valeur ; son périmètre de privilèges est **spécifié et testé en code**, mais l'isolation réseau et la configuration du proxy ne seront prouvées qu'avec `infra/compose`.

### 5.4 Plan d'action priorisé (sprint)

| Priorité | Action | Pilier | Échéance |
|---|---|---|---|
| P1 | Livrer `infra/compose` (3 réseaux, durcissement) et lancer `audit.sh` | Infra / Cyber | J2 |
| P1 | Playbooks `waf_deny_ip.yml`, `pg_restore.yml` + **job de dump planifié** (condition du RPO) | Infra | J3 |
| P1 | `scripts/verify_tx` et rejeu des 4 scénarios, relevé des MTTR | Dév / Infra | J3-J4 |
| P2 | Clé age réelle + `secrets.enc.env` ; relecture `gitleaks` | Cyber | J2 |
| P2 | Règles SOC Loki sur les `event` normalisés | Cyber / Infra | J3 |
| P3 | Mettre à jour cette cotation avec les MTTR mesurés et les incidents du chaos engineering | Transformation | J4 |
