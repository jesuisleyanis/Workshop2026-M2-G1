# PCA / PRA — RESILIENCE-ALPHA

> Couvre **R17**. Version **v1 (J1, 2026-10-19)**. Les objectifs RTO/RPO ci-dessous sont des **cibles dérivées des paramètres réels** du moteur et de l'architecture ; elles sont **validées ou révisées par la mesure** en recette J3/J4 (§4.3). Aucune valeur mesurée n'est annoncée ici : au 2026-10-19 aucun rejeu de bout en bout n'a encore eu lieu.
> Analyse de risques associée : `docs/ebios-rm.md`. Cadre réglementaire : `docs/nis2-dora.md`.

**Légende** : **[R]** réalisé dans le dépôt · **[S]** spécifié mais composant pas encore livré · **[M]** à mesurer en recette.
Dépendances **encore non livrées** dont dépendent les objectifs : `infra/compose`, `infra/ansible/playbooks/{waf_deny_ip,pg_restore}.yml`, **job de dump Postgres planifié** (aucune implémentation de sauvegarde dans le dépôt, seul le contrat `restore_pg_dump` existe), `scripts/verify_tx`.

---

## 1. Services critiques et dépendances

| Id | Service | Criticité | Dépend de | Effet d'une panne de la dépendance |
|---|---|---|---|---|
| **S1** | **Paiement** (`payment-api`, via WAF + front) | **Vitale** | Postgres (`/ready`), WAF. **Valide le JWT localement** (HS256 + `JWT_SECRET`) : pas d'appel à `auth` à chaque requête | Postgres KO : paiement KO. `auth` KO : les sessions déjà émises (15 min) continuent de fonctionner |
| **S2** | **Authentification** (`auth`) | **Haute** | Postgres | Pas de nouvelle connexion ; paiement des sessions actives non touché |
| **S3** | **Données** (Postgres 16, réseau `data` interne) | **Vitale** (porte VM2) | volume, dumps | Perte ou corruption : perte d'intégrité (ER2) |
| **S4** | **WAF** (Nginx + CRS) | **Vitale** (seule porte d'entrée) | `blocked_ips.conf`, `nginx.conf` | WAF KO : plus aucun accès externe (S1, S2 inaccessibles) |
| **S5** | **Chaîne de reprise** : collector, detector (modèle v1.0.0), moteur de remédiation, Prometheus, Loki | **Haute** pour l'**autonomie**, nulle pour le paiement | Prometheus -> collector -> detector -> remédiation ; remédiation -> proxy Docker, Ansible, auth, Loki, `verify_tx` | Panne : le paiement continue **mais la reprise n'est plus autonome** (mode dégradé = runbook manuel, §5.5) |
| **S6** | Supervision (Grafana, dashboard, Alertmanager), assistant RAG | Moyenne / faible | S5 | Perte de visibilité seulement ; assistant arrêtable sans impact |

Principe de conception à retenir : **le plan de reprise ne doit pas être sur le chemin critique du paiement**. S5 est séparé de S1 (réseaux `app`/`obs`, services distincts, assistant isolé de l'automate).

## 2. Définitions de mesure (pour que RTO et MTTR soient comparables)

| Indicateur | Définition exacte | Source |
|---|---|---|
| **Délai de détection** `D` | début de l'attaque (`attacks/.runlog`, horodatage `START`) -> événement `anomaly_detected` | Loki + `.runlog` |
| **MTTD** (moteur) | détection -> **première action** de remédiation | `resilience_mttd_seconds{incident_id}` |
| **MTTR** (moteur) | détection (`detected_at`) -> `verify_tx` OK (`remediation_verified`) | `resilience_mttr_seconds{incident_id}`, journal `incidents.db`, API `/incidents` |
| **RTO perçu** | début de l'attaque -> `verify_tx` OK = **`D` + MTTR** | calcul `.runlog` + journal |

**Point de rigueur** : `resilience_mttr_seconds` **ne contient pas** le délai de détection `D` (il part de `detected_at`). Annoncer le MTTR comme le RTO sous-estimerait l'indisponibilité vécue. Le RTO est donc fixé sur `D + MTTR`.
Contrainte de rétention : les gauges `resilience_mttd/mttr_seconds` ne gardent que les **20 derniers incidents** (`MAX_GAUGE_INCIDENTS`) ; la série longue se lit dans le journal SQLite et dans Loki (`remediation_verified`).

## 3. Objectifs RTO / RPO chiffrés

### 3.1 Construction du RTO à partir de paramètres réels

| Composante | Valeur | Source |
|---|---|---|
| Collecte du vecteur de features | toutes les **15 s** ; fenêtre `rate()` **30 s** | `ml/collector/app.py` (`COLLECT_INTERVAL_SECONDS`, `PROM_RATE_WINDOW`) |
| Vérification après action | **5 essais x 3 s** (`verify_retries`, `verify_interval_s`) | `remediation/config.py` |
| Cooldown entre tentatives | **60 s**, **3 tentatives** max puis escalade | `remediation/decision_table.yml` |
| Borne par action | 300 s (`action_timeout_s`) | `remediation/config.py` |

- `D` typique : 15 à 45 s (une à trois collectes avant que le score franchisse le seuil 0,6296) [M].
- Reprise nominale : actions + vérification. Pour `service_flood` : playbook WAF + reload (estimé 5-10 s), `verify_tx`, redémarrage `payment-api` (estimé 5-15 s), `verify_tx` ; **MTTR estimé 15-30 s** [M].
- **Borne dure avant escalade** : 3 tentatives, 2 cooldowns de 60 s -> de l'ordre de **3 à 5 min** (estimation à confirmer [M]). Au-delà, le moteur journalise `remediation_failed` et notifie l'opérateur : la reprise **n'est plus** autonome.

### 3.2 Objectifs par service

| Service | **RTO cible (perçu)** | **RPO cible** | Justification |
|---|---|---|---|
| **S1 Paiement** (`service_flood`) | **<= 60 s** nominal ; **<= 5 min** borne avant escalade | **0** (aucune donnée perdue : redémarrage sans restauration) | `D` <= 30 s + MTTR <= 30 s ; cohérent avec la contrainte du Clip Chrono (<= 60 s, attaque -> vérification) |
| **S2 Authentification** (`auth_abuse`) | **<= 60 s** (login dégradé, pas d'arrêt du paiement) | 0 (pas de restauration) ; comptes créés après le dernier dump perdus en cas de restauration S3 | action = blocage + appel HTTP interne, plus rapide qu'un redémarrage |
| **S3 Données** (`data_corruption`) | **<= 2 min** sur le jeu de démo ; **dépend de la taille** en réel : `RTO = D + playbook + durée pg_restore + verify` | **<= 5 min** (dump toutes les 5 min [S], **condition non remplie tant que le job de dump n'existe pas**) | données fictives de petite taille ; la restauration est la seule réponse valable (intégrité, pas disponibilité) |
| **S4 WAF** (conf, deny-list) | **<= 30 s** (reload/restart) | **0** pour la configuration (code versionné) ; deny-list reconstructible depuis le journal d'incidents | `nginx -s reload` ou restart conteneur |
| **S5 Chaîne de reprise** | **<= 5 min** (redémarrage manuel ou Compose) | **0** pour le modèle (artefact versionné, `sha256` vérifié au chargement, ré-entraînable : `python -m ml.training.train --seed 42`) ; journal `incidents.db` : **dernier volume** | hors chemin critique du paiement |
| **S6 Supervision / assistant** | best effort <= 15 min | non critique | |
| **Web attack** (`web_attack`) | **aucune interruption attendue** (le CRS répond 403 en ligne) ; blacklist <= 30 s | 0 | l'attaque est bloquée avant l'application ; le moteur confirme puis liste noire |

### 3.3 Objectifs PRA (sinistre majeur : perte de l'hôte ou des volumes)

| Objectif | Cible | Condition |
|---|---|---|
| **RTO PRA** (reconstruction sur une autre machine) | **<= 30 min** (images en cache local), **<= 60 min** sinon | `git clone`, clé age (hors archive), `scripts/decrypt-secrets.sh`, `make up`, restauration du dump, `make verify` |
| **RPO PRA** | **<= 1 h** | copie **hors hôte** des dumps toutes les heures [S] (clé USB / second PC) ; **inexistante aujourd'hui** |

Statut : objectif **sur papier, non éprouvé** (non démontrable dans le sprint). Il est affiché pour que la direction voie l'écart avec la reprise automatique : sur sinistre majeur, **la reprise n'est plus zero-touch**.

### 3.4 Règle de cohérence RTO / mesure (anti-affichage)

Après >= 10 rejeux par scénario : `RTO_retenu = arrondi_sup(1,5 x p95(D + MTTR))`. Si cette valeur dépasse la cible du §3.2, **on révise la cible dans ce document, on ne retouche pas la mesure**. Le tableau suivant est à compléter en recette (J3/J4) depuis `resilience_mttr_seconds` et `attacks/.runlog` :

| Scénario | `D` p95 | MTTR p95 | RTO perçu p95 | Cible §3.2 | Écart |
|---|---|---|---|---|---|
| service_flood | [M] | [M] | [M] | <= 60 s | |
| auth_abuse | [M] | [M] | [M] | <= 60 s | |
| web_attack | [M] | [M] | [M] | blocage immédiat | |
| data_corruption | [M] | [M] | [M] | <= 2 min | |

## 4. Scénarios couverts, et non couverts

### 4.1 Couverts par la reprise automatique (table `remediation/decision_table.yml`)

| Scénario (`attacks/scenarios/`) | `incident_type` | Famille de réponse | Actions (ordre) | PCA ou PRA |
|---|---|---|---|---|
| `service_flood` | service_flood | **Disponibilité** | `waf_block_ip` -> `restart_service(payment-api)`, `verify_tx` après chaque action modifiante | PCA |
| `auth_abuse` | auth_abuse | Disponibilité / contrôle d'accès | `waf_block_ip` -> `tighten_rate_limit(auth, x0.5)` | PCA |
| `web_attack` | web_attack | Prévention / confinement | `confirm_waf_block` -> `waf_blacklist_ip` | PCA |
| `data_corruption` | data_corruption | **Correction d'intégrité** | `restore_pg_dump(latest)` **seule** (ni restart ni recreate : invariant de `decision.py`) | **PRA** (données) |
| (aucun) | unknown | Escalade | `dry_run_report` seul (aucune action destructive), puis `notify_operator` | hors reprise |

### 4.2 Sinistres **non** couverts automatiquement (assumé)

| Sinistre | Pourquoi | Palliatif |
|---|---|---|
| **Panne simple d'un conteneur** (non attaque) | pas de type d'incident dédié : classé `unknown` donc rapport + escalade, pas d'action | healthcheck + politique de redémarrage Compose [S] ; à éprouver au **chaos engineering J4** |
| **Perte de l'hôte / des volumes** | un seul hôte, dumps sur le même hôte | PRA §3.3 (reconstruction manuelle) |
| **Panne du moteur de remédiation ou du proxy Docker** | SPOF de l'autonomie | runbook manuel §5.5 |
| **Compromission d'un secret** (`JWT_SECRET`...) | pas de détection ni d'action dédiée | rotation manuelle : régénérer via SOPS, redéployer `auth` et `payment-api` (invalide toutes les sessions) |
| **DDoS volumétrique distribué** | le blocage de source ne suffit pas | hors périmètre ; transfert (scrubbing opérateur) |

### 4.3 Plan d'essai (preuves)

- Rejeu des 4 scénarios depuis le **PC Attaquant** (`attacks/run.sh <scenario>`), remise à l'état « avant » par `attacks/reset.sh` entre deux essais ; >= 10 rejeux de `service_flood` et `data_corruption`.
- Relevé `D`, MTTR, nombre de tentatives, résultat final (`closed` / `escalated`) depuis le journal ; alimente §3.4.
- Test de restauration **à blanc** : restaurer un dump dans une base temporaire et vérifier les invariants (§5.2) ; à faire **avant** tout RPO affiché.
- Chaos J4 : arrêt d'un conteneur, perte du moteur, dump absent ou illisible, `verify_tx` KO persistant (doit aboutir à `escalated` après 3 tentatives, sans boucle infinie).

## 5. Procédures de restauration

### 5.1 `service_flood` et `auth_abuse` (automatique, sans perte de données)

1. Détection : le detector émet `anomaly_detected` et un `POST /events` (token `REMEDIATION_TOKEN`) au format `docs/contracts.md` §3. Idempotence : un `event_id` rejoué ou un incident déjà en cours est ignoré ; le cooldown de 60 s évite la ré-action.
2. Le moteur applique la règle : **blocage de l'IP source** (`waf_deny_ip.yml` : écriture dans `blocked_ips.conf`, idempotent, puis reload Nginx ; refus de bloquer `127.0.0.1`, `::1`, `192.168.137.1`). Pour `auth_abuse` : appel `POST /internal/tighten-rate-limit` (token `INTERNAL_TOKEN`).
3. `service_flood` : **redémarrage** de `payment-api` via `docker-socket-proxy` (`POST /containers/{id}/restart`, services autorisés : `payment-api`, `auth`, `front`).
4. `verify_tx` (jusqu'à 5 essais x 3 s) : OK -> incident clos, MTTR publié ; KO -> action suivante, puis nouvelle tentative après cooldown, puis **escalade** après 3.
5. Remise en l'état de référence (après essai) : `attacks/reset.sh` vide la deny-list et re-seed. En exploitation réelle, **lever** les mesures (deny-list, rate-limit) est une décision humaine post-incident (§8, R5).

### 5.2 `data_corruption` : restauration d'intégrité (`restore_pg_dump`)

Action : `restore_pg_dump` (`remediation/actions/postgres.py`), paramètre `backup` = `latest` ou nom de dump simple (regex sans `/` ni `..`, pas de traversée de chemin). Elle lance **uniquement** le playbook nommé `pg_restore.yml` (variables `backup`, `incident_id` ; ni le playbook ni ses variables ne viennent de l'événement). Idempotente : restaurer deux fois le même dump donne le même état.

**Exigences pour `infra/ansible/playbooks/remediation/pg_restore.yml`** [R] (réalisées, ticket #8 ; exécuté dans le conteneur remediation, voir `infra/ansible/README.md`) :
- `pg_restore --clean --if-exists --single-transaction` : atomique, un échec laisse l'état précédent, jamais un état à moitié restauré ;
- intégrité du dump vérifiée **avant** de toucher à la base (`pg_restore --list`) ; tables en quarantaine (`*__corrupted`) purgées d'abord ;
- réseau `data` uniquement ; secrets via `POSTGRES_PASSWORD` (SOPS → environnement), jamais en clair dans le playbook ; contrôle `SELECT count(*)` sur `users/accounts/transactions` après restauration.

**Après restauration, au-delà de `verify_tx`** (le sujet précise que des données incohérentes = problème non résolu) : contrôler les invariants : `balance_cents >= 0` (contrainte DB), somme des soldes = somme du dump de référence, clés étrangères valides, absence de transaction `created` orpheline. `verify_tx` ne prouve qu'**une** transaction de bout en bout.

**Dump de référence** [S] : `pg_dump -Fc` toutes les **5 min**, rétention >= 12 dumps (1 h) pour pouvoir remonter plus loin que `latest`, stockés hors du conteneur Postgres. Choix de conception à trancher par le pilier Infra : conteneur dédié `pg-backup` sur le réseau `data`, ou playbook `pg_backup.yml` planifié.

**Perte attendue** : toutes les transactions entre le dernier dump et l'incident (<= RPO). Réconciliation possible **partielle** : l'événement `transaction_created` journalise l'`id` et l'utilisateur, **pas le montant ni les comptes** ; les opérations perdues sont identifiables mais pas rejouables (voir §8, R1).

### 5.3 `web_attack`

`confirm_waf_block` (lecture seule Loki : `{service="waf"} |= "waf_blocked"` sur 120 s, filtré par IP) puis `waf_blacklist_ip` (liste `permanent`). Aucune restauration de service nécessaire : le CRS a répondu 403 avant l'application. Retour arrière : retirer la ligne de `blocked_ips.conf` + reload (ou `attacks/reset.sh`).

### 5.4 PRA : reconstruction sur une autre machine (manuel, non éprouvé)

1. `git clone` du dépôt ; récupérer la **clé age** par le canal privé (jamais dans l'archive).
2. `export SOPS_AGE_KEY_FILE=...` puis `scripts/decrypt-secrets.sh` (produit le `.env` local ignoré par git).
3. `make up` (Compose, [S]) ; playbooks de déploiement Ansible (R6, [S]).
4. Restaurer le dernier dump **copié hors hôte** (§3.3).
5. `make verify` (`scripts/verify_tx`, code 0 = OK) puis contrôle des invariants §5.2.
6. Régénérer la deny-list depuis le journal d'incidents si nécessaire.

### 5.5 Mode dégradé (reprise autonome indisponible)

Déclencheurs : escalade `remediation_failed`, moteur ou proxy en panne, type `unknown`. Un opérateur applique la **même séquence que l'automate** (`blocked_ips.conf` + reload, redémarrage du service, restauration du dump) puis `make verify`. Toute intervention de ce type **met fin au caractère zero-touch** de l'incident : elle est consignée dans le post-mortem. (Elle est interdite dans la démo notée.)

### 5.6 Inventaire des playbooks (lien avec `remediation/actions/runner.py`)

| Playbook | Appelé par | Variables | État au 2026-10-19 |
|---|---|---|---|
| `waf_deny_ip.yml` | `waf_block_ip`, `waf_blacklist_ip` | `deny_ip`, `deny_list` (temporary / permanent), `incident_id` | [S] `infra/ansible/playbooks/` vide |
| `pg_restore.yml` | `restore_pg_dump` | `backup`, `incident_id` | [S] idem |
| playbooks de déploiement et de reprise (R6) | opérateur / `make up` | — | [S] |

`ALLOWED_PLAYBOOKS` ne contient **que** ces deux noms : tout autre playbook est refusé par le moteur.
**À trancher à l'écriture** : le mécanisme de rechargement de Nginx. `docker-socket-proxy` n'autorise que `restart` ; **ne pas élargir le proxy à `exec`** pour y parvenir (cela ouvrirait une exécution arbitraire dans les conteneurs). Privilégier un volume partagé pour la deny-list et un signal/restart du seul WAF.

## 6. Responsabilités

Principe directeur : **l'humain décide avant, l'automate exécute pendant, l'humain analyse après.** La décision est portée par `decision_table.yml` (versionnée, revue par PR) ; l'exécution par le moteur (privilèges bornés) ; le retour d'expérience par l'équipe.

| Activité | Direction | RSSI / Cyber | Continuité (PCA/PRA) | Infra / Exploitation | Dév / Métier | IA / Data |
|---|---|---|---|---|---|---|
| Fixer RTO/RPO et accepter les risques résiduels | **A** | C | R | C | C | I |
| Valider la table de décision et ses invariants | I | **A** | C | C | R | C |
| Détection (seuil, ré-entraînement, dérive) | I | C | I | I | I | **R/A** |
| Exécution des actions (playbooks, proxy) | I | C | I | **R/A** | I | I |
| Vérification de reprise (`verify_tx`, invariants) | I | I | C | R | **R/A** | I |
| Sauvegardes, copie hors hôte, test de restauration | I | C | **A** | **R** | C | I |
| Escalade `remediation_failed` / mode dégradé | I | **R/A** | C | R | C | C |
| Gestion des secrets, rotation | I | **A** | I | R | C | I |
| Post-mortem, mise à jour des documents | I | R | **A** | C | C | C |
| Notification d'incident majeur (réglementaire) | **A** | R | C | C | I | I |

R = réalise, A = rend compte, C = consulté, I = informé. Les noms sont à renseigner dans `ROADMAP.md` (référents de piliers « à renseigner » au 2026-10-19) ; une personne peut cumuler plusieurs rôles (sujet §3).

## 7. Arbitrages assumés

| Décision | Choix du démonstrateur | Alternative et raison de ne pas la prendre ici |
|---|---|---|
| RPO base de données | **dump toutes les 5 min** (simple, vérifiable, coût négligeable sur données fictives) | WAL archiving / PITR (RPO proche de 0) : complexité et RAM hors budget 16 Go ; **recommandé en réel** |
| Restauration `latest` automatique | automatique en démo | en réel, **validation humaine** avant une restauration destructive (perte jusqu'au RPO) ; le mécanisme `dry_run` existe déjà |
| Un seul hôte | oui (contrainte du sujet) | réplication et second site : hors périmètre ; documenté en risque résiduel |
| Détection | ML + garde-fou statistique | règles seules : écartées par le sujet (§3.3) ; limite : baseline synthétique |

## 8. Risques résiduels après reprise

| Id | Risque résiduel | Cause vérifiable | Effet | Parade / décision |
|---|---|---|---|---|
| **R1** | **Perte de transactions jusqu'au RPO** après restauration | restauration = retour à l'état du dernier dump ; `transaction_created` ne journalise ni montant ni comptes | opérations non rejouables | journaliser montant/comptes (ou hash) ; en réel PITR ; **acceptation direction** |
| **R2** | **Dump déjà corrompu** restauré par `latest` | `latest` = dernier dump sans contrôle de contenu | retour à un état altéré, `verify_tx` peut passer | rétention >= 12 dumps, contrôle d'invariants avant rotation, `backup=<nom>` pour remonter |
| **R3** | **Corruption silencieuse non détectée** | le signal retenu est `db_errors_per_s` + `verify_tx` KO | corruption sans erreur DB ignorée | contrôles d'intégrité périodiques (invariants §5.2) |
| **R4** | **Rotation d'IP / attaque distribuée** | blocage par IP source uniquement | le flood reprend ; escalade après 3 tentatives | transfert (scrubbing) ; limites par compte ; hors périmètre |
| **R5** | **Mesures sans retour arrière** | deny-list sans expiration côté moteur ; rate-limit durci levé seulement au redémarrage de `auth` ; **`auth` ne dédoublonne pas `Idempotency-Key`** donc re-durcissement à chaque tentative (10 -> 5 -> 2 -> 1/min) | pénalise des utilisateurs légitimes | corriger le dédoublonnage ; expiration de la deny-list `temporary` ; levée post-incident par décision humaine |
| **R6** | **Faux positif ML** | seuil 0,6296, 0/2000 FP sur baseline **synthétique** | redémarrage inutile de `payment-api` (interruption courte auto-infligée) | cooldown 60 s ; ré-entraînement sur trafic réel avant production |
| **R7** | **Points uniques de défaillance** : hôte, WAF, Postgres, moteur | architecture imposée | arrêt total ou perte d'autonomie | PRA §3.3, mode dégradé §5.5 |
| **R8** | **Sauvegardes sur le même hôte** | aucune copie hors hôte | perte de l'hôte = perte des dumps ; RPO PRA non tenu | copie hors hôte horaire [S] |
| **R9** | **`verify_tx` trop étroit** | une transaction de contrôle | incohérences globales non vues | contrôle d'invariants §5.2 |
| **R10** | **Journal d'incidents local** | SQLite `incidents.db` | perte du journal si le volume n'est pas persistant | volume dédié ; export vers Loki (`remediation_*`) |
| **R11** | **Sessions JWT non révocables** | JWT stateless 15 min, secret partagé | un jeton volé reste valide jusqu'à expiration | rotation de `JWT_SECRET` en cas de compromission ; JWT asymétrique en réel |
| **R12** | **Restauration pendant écritures actives** | pas de quiescence des écrivains (le moteur ne peut redémarrer que 3 services et ne coupe pas le trafic) | écritures concurrentes perdues ou bloquées par les verrous | `--single-transaction` ; blocage préalable de la source (déjà dans le flux `service_flood`) ; étudier une mise en maintenance du WAF |

**Synthèse pour la direction** : la reprise automatique tient la **disponibilité** (RTO de l'ordre de la minute, RPO nul) pour trois scénarios sur quatre ; pour l'**intégrité** elle restaure, mais **au prix d'une perte bornée au RPO**, que la direction doit accepter explicitement. Deux conditions manquent pour que ces chiffres soient exacts : le **job de dump planifié** (sans lui le RPO n'est pas tenu) et la **mesure** des MTTR (sans elle le RTO reste une cible).
