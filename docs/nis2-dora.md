# NIS2 / DORA — RESILIENCE-ALPHA

> Couvre **R18**. Version **v1 (J1, 2026-10-19)**. Posture : **conseil à une direction**. Pour chaque exigence on dit ce que le prototype **prouve** (avec une preuve vérifiable), ce qu'il **ne prouve pas** en 4 jours, et ce que l'on recommande.
> Liens : risques `docs/ebios-rm.md`, continuité `docs/pca-pra.md`, interfaces `docs/contracts.md`.
> **Avertissement de méthode** : les références d'articles ci-dessous sont données de bonne foi et **à recouper avec les textes officiels (EUR-Lex) avant remise du dossier** ; le statut de transposition nationale de NIS2 et l'autorité compétente exacte sont **à confirmer par le juridique**.

**Légende de preuve** : **Démontré** = comportement présent dans le dépôt, vérifiable · **Partiel** = présent mais limité, limite dite · **Non démontrable en 4 jours** = hors portée d'un prototype, dit explicitement.
Statut de livraison : **[R]** réalisé · **[S]** spécifié, pas encore livré (au 2026-10-19 : `infra/*`, `dashboard/`, `scripts/verify_tx` encore absents).

---

## 1. Cadrage : quelle entité, quel texte s'applique

**Hypothèse de travail** : entité financière **fictive** exploitant une plateforme de paiement (type établissement de paiement). Conséquences :

| Texte | Portée pour cette entité | Ce qu'on en retient |
|---|---|---|
| **DORA** (Règlement UE 2022/2554, applicable depuis le 17 janv. 2025) | **Applicable directement** : c'est le texte sectoriel des entités financières | 5 piliers : gestion du risque TIC (art. 5-16), incidents (17-23), tests de résilience (24-27), risque lié aux tiers (28-44), partage d'information (45) |
| **NIS2** (Directive UE 2022/2555) | Le secteur bancaire/financier est dans son champ ; **DORA est considéré comme acte sectoriel** (art. 1 §2 DORA) qui prime pour la gestion du risque TIC et la notification d'incident | NIS2 reste pertinent comme **grille de mesures** (art. 21) et de gouvernance (art. 20) ; ses délais de notification (art. 23 : alerte précoce 24 h, notification 72 h, rapport final 1 mois) servent de repère |

**Recommandation de cadrage** : traiter **DORA comme référentiel principal** et NIS2 art. 21 comme grille de contrôle croisée, sans doubler les processus (une seule chaîne d'incident, un seul registre de risques).

## 2. Ce que le prototype démontre, et ce qu'il ne démontre pas

### 2.1 Exigences **démontrables** par le prototype

| Exigence (DORA / NIS2) | Preuve dans le prototype | Niveau | Limite honnête |
|---|---|---|---|
| **Détection d'activités anormales** (DORA art. 10 ; NIS2 art. 21(2)(b)) | Modèle IsolationForest v1.0.0 (seuil 0,6296, 0/2000 faux positifs, détection 95,7-100 % selon scénario ; 100 % avec garde-fou) ; métrique `resilience_anomaly_score` ; événement `anomaly_detected` (`ml/detector/core.py`, `baseline_stats.json`) | **Démontré** | baseline et attaques **synthétiques** ; pas de trafic réel ; type d'incident étiqueté par heuristique |
| **Journalisation et traçabilité** (DORA art. 9-10 ; NIS2 art. 21) | Logs JSON normalisés (`ts`, `level`, `service`, `event`, `request_id`, `client_ip`, `incident_id`) ; corrélation de bout en bout ; Promtail -> Loki ; journal d'incident SQLite + timeline horodatée de chaque action et vérification (`remediation/journal.py`, `timeline.py`) | **Démontré** (formats [R], chaîne Loki [S]) | pas de rétention ni d'immuabilité définies ; `transaction_created` ne trace pas le montant ; mots de passe jamais journalisés |
| **Réponse et reprise** (DORA art. 11 ; NIS2 art. 21(2)(c)) | Remédiation autonome pilotée par `decision_table.yml`, vérifiée par `verify_tx`, avec cooldown (60 s), `max_attempts` (3), `dry_run`, escalade `notify_operator` ; distinction explicite disponibilité / intégrité (`restore_pg_dump`) | **Démontré** sur les 4 scénarios (essai à confirmer en recette [M]) | reprise **autonome** sur incidents bornés ; sinistre majeur = manuel (`docs/pca-pra.md` §3.3) |
| **Sauvegarde et restauration** (DORA art. 12 ; NIS2 art. 21(2)(c)) | Action `restore_pg_dump` idempotente, paramètre validé, playbook nommé | **Partiel** | **job de dump planifié et playbook `pg_restore.yml` non livrés** [S] ; pas de copie hors hôte ; pas de test de restauration périodique |
| **Tests de résilience** (DORA art. 24-25 ; NIS2 art. 21(2)(f)) | Banc d'essai `attacks/` : 4 scénarios déclarant signal, `incident_type`, remédiation attendue, critère de réussite ; garde-fous (<= 100 req/s, <= 60 s, kill-switch `run.sh --stop`, `reset.sh`) ; tests `attacks/tests` (4 verts) ; chaos J4 prévu | **Partiel** | c'est un test de **scénarios** ; **pas** un programme annuel documenté, **pas** un test d'intrusion piloté par la menace (TLPT, art. 26) |
| **Gestion des secrets et cryptographie** (DORA art. 9 ; NIS2 art. 21(2)(h)) | SOPS + age (clé privée hors git), `*_FILE` côté moteur, `gitleaks` pre-commit, `audit.sh` avant packaging, bcrypt (12 tours), JWT à `alg` épinglé ; TLS sur le WAF | **Partiel** | clé age réelle et `secrets.enc.env` à créer [S] ; JWT HS256 **symétrique partagé** ; TLS auto-signé ; pas de rotation automatisée |
| **Contrôle d'accès, moindre privilège, segmentation** (DORA art. 9(4) ; NIS2 art. 21(2)(i)) | Seul le WAF exposé ; réseau `data` interne ; moteur : proxy Docker à verbes limités + liste blanche client + playbooks nommés + token + hors `edge` ; conteneurs non-root, `cap_drop: ALL` (`security/hardening/`) | **Partiel** (code [R], isolation réseau et compose [S]) | **pas de MFA** (NIS2 art. 21(2)(j)) ; pas de verrouillage par compte |
| **Gestion des vulnérabilités** (NIS2 art. 21(2)(e)) | `trivy` et `gitleaks` documentés (`hardening.md`) | **Partiel** | non exécutés en continu (pas de CI, décision d'équipe) |
| **Alimentation de la classification d'incident** (DORA art. 17-18) | Le journal fournit les données de base (§2.3) | **Partiel** | aucun critère de classification automatisé |

### 2.2 Exigences **non démontrables** en 4 jours (dit explicitement)

| Exigence | Pourquoi le prototype ne peut pas la démontrer | Ce que le dossier peut apporter |
|---|---|---|
| **Gouvernance par l'organe de direction** (DORA art. 5 ; NIS2 art. 20) : approbation du cadre TIC, supervision, formation des dirigeants | exige une direction réelle, des décisions et des preuves dans le temps | documents d'**aide à la décision** (EBIOS, PCA/PRA, arbitrages §3) ; **aucune approbation réelle n'existe** |
| **Reporting réglementaire des incidents majeurs** (DORA art. 19 ; NIS2 art. 23) : notification initiale, rapport intermédiaire, rapport final, avec délais courts, vers l'autorité compétente | aucun processus ni modèle de notification n'est implémenté ; aucune autorité n'est jointe ; les délais n'ont pas été testés | mapping des champs de rapport vers le journal (§2.3) et recommandation de procédure (§3, D6) |
| **Gestion du risque lié aux prestataires tiers** (DORA art. 28-30, registre d'informations ; NIS2 art. 21(2)(d)) : due diligence, clauses contractuelles, stratégies de sortie | aucun contrat ni prestataire réel | inventaire des dépendances **réelles** du projet comme amorce de registre (§2.4) |
| **Test d'intrusion piloté par la menace (TLPT)** (DORA art. 26) | réservé aux entités désignées, avec testeurs indépendants, cycle de plusieurs années | le banc d'essai interne en est un **précurseur**, pas un équivalent |
| **Partage d'informations sur les menaces** (DORA art. 45) | pas de communauté | — |
| **Gestion de crise et communication** (DORA art. 14 ; NIS2 art. 21(2)(c)) | `notify_operator` journalise et notifie un webhook ; pas de cellule de crise ni de communication clients | rôles du `docs/pca-pra.md` §6 |
| **Formation, hygiène numérique, RH** (NIS2 art. 21(2)(g)(i)) | hors périmètre technique | recommandation (§3, D8) |
| **Revue indépendante du cadre TIC** (DORA art. 6(6)) | pas d'audit interne ou externe | recommandation (§3, D8) |

### 2.3 Du journal d'incident aux champs d'un rapport d'incident (DORA art. 19)

Le prototype ne produit pas le rapport, mais il **capture les données que le rapport exige** :

| Information attendue | Source dans le prototype | Disponibilité |
|---|---|---|
| Date/heure de détection, durée de l'incident | `detected_at`, `resilience_mttd_seconds`, `resilience_mttr_seconds`, journal `incidents.db` | **Oui** (MTTR partant de la détection : ajouter le délai `D`, `docs/pca-pra.md` §2) |
| Type et cause apparente | `incident_type`, `features_top` (feature + z-score), `evidence` (requête Prometheus/Loki) | **Oui** |
| Services et fonctions touchés | `service`, clé d'incident `incident_type:service` | **Oui** |
| Mesures prises et résultat | `remediation_action`, `remediation_verified` ou `remediation_failed`, timeline horodatée, nombre de tentatives | **Oui** |
| Origine (IP source) | `client_ip` (X-Forwarded-For réécrit par le WAF), `source_ip` de l'événement | **Oui** |
| Clients/transactions touchés | non calculé | **Non** : `transaction_created` ne porte pas le montant ; nombre de clients affectés non agrégé |
| Perte de données | RPO théorique uniquement | **Non mesuré** |
| Impact économique, étendue géographique, criticité | n/a | **Non** (jugement humain) |

### 2.4 Dépendances tierces **réelles** du projet (amorce de registre, DORA art. 28)

| Dépendance | Rôle | Criticité | Stratégie de sortie / remarque |
|---|---|---|---|
| Images `python:3.12-slim`, `nginx:alpine`, `postgres:16` | base de tous les services | Haute | images épinglées par version/digest ; registre local pour le PRA |
| `tecnativa/docker-socket-proxy` | seul accès du moteur à Docker | **Haute (sécurité)** | alternative : proxy maison ; surveiller les vulnérabilités |
| ModSecurity + OWASP CRS | WAF | Haute | règles versionnées ; le WAF est le seul point exposé |
| FastAPI, SQLAlchemy, scikit-learn, joblib, ansible-runner | code applicatif, ML, exécution de playbooks | Haute | `joblib` désérialise du code : **modèle vérifié par `sha256`** avant chargement (`ml/detector/model.py`) |
| Prometheus, Loki, Promtail, Grafana, Alertmanager, cAdvisor | observabilité, SOC | Moyenne | Elastic écarté pour la charge mémoire |
| Ollama + modèle <= 8B (`qwen2.5:7b` ou `llama3.1:8b`), LangChain, Chroma | assistant RAG | Faible (non critique, isolé de l'automate) | arrêt sans impact sur la reprise |
| SOPS, age | secrets | Haute | Vault en alternative |

Statut : **registre technique partiel** ; les volets contractuels (clauses, audit, sous-traitance, sortie) ne sont **pas** démontrables dans le sprint.

---

## 3. Arbitrages et recommandations à la direction

| Id | Décision | Options | **Recommandation** | Fondement vérifiable | Effort |
|---|---|---|---|---|---|
| **D1** | Faut-il automatiser la reprise ? | Tout automatique / tout manuel / hybride | **Hybride** : automatique pour les mesures **réversibles et bornées** (blocage IP, redémarrage, durcissement), **validation humaine avant une restauration destructive** en production (`data_corruption` perd jusqu'au RPO) ; la démo notée reste 100 % automatique | invariants de `remediation/decision.py` ; `dry_run` ; type `unknown` sans action destructive | S |
| **D2** | Quel niveau de RPO/RTO financer ? | dump 5 min (démo) / WAL + PITR / réplica | démo : dump 5 min. **Production : WAL archiving + réplica** pour viser un RPO proche de 0 sur les données financières ; RTO de reprise automatique conservé | `docs/pca-pra.md` §3, R1-R2 ; perte non rejouable (montant non journalisé) | L |
| **D3** | Détection par ML ou par règles ? | règles seules / ML seul / ML + garde-fou | **ML + garde-fou statistique documenté** ; **avant production** : collecter 2 à 4 semaines de trafic réel, ré-entraîner, fixer un processus de revue du seuil (le modèle est lui-même un risque : DORA art. 9-10) | 0 faux positif et >= 95 % de détection **sur données synthétiques** ; limites dites | M |
| **D4** | Comment donner des droits élevés à l'automate ? | socket Docker brut / proxy à verbes limités / pas d'automate | **Proxy restreint, jamais le socket brut** ; ajouter trace d'audit immuable des actions et revue périodique des listes blanches | `remediation/actions/docker_proxy.py` (liste blanche méthode+chemin), `runner.py` (`ALLOWED_PLAYBOOKS`), `audit.sh` | S |
| **D5** | SIEM complet ou fonction SOC intégrée ? | Wazuh/Elastic / règles Loki-Grafana | démo : **fonction SOC intégrée** (contrainte 16 Go). **Production** : SIEM avec rétention définie, détection 24/7 (SOC ou service managé) | `docs/contracts.md` §1 (événements normalisés), journal d'incident | L |
| **D6** | Comment tenir les délais de notification ? | rien / modèle manuel / automatisé | **Écrire la procédure et le modèle de notification** (initiale, intermédiaire, finale) alimentés par le journal (§2.3), désigner un responsable, **les répéter** une fois par an | §2.3 ; les délais DORA/NIS2 sont plus courts que le MTTR humain d'une reprise manuelle | M |
| **D7** | Secrets : SOPS ou Vault ? | SOPS+age / Vault / HSM | démo : **SOPS** (git-natif, léger). **Production** : Vault/HSM, rotation planifiée, **JWT asymétrique** (la compromission d'un service ne permettrait plus de forger des jetons) | `security/sops/README.md`, R11 et SO5 | M |
| **D8** | Tiers et gouvernance : par où commencer ? | — | registre d'informations des tiers (§2.4), approbation du cadre TIC par la direction, MFA, formation, audit indépendant | §2.2 | M |

### Feuille de route proposée

| Horizon | Actions |
|---|---|
| **30 jours** | Désigner le responsable DORA ; approuver le cadre TIC ; écrire la procédure de notification ; livrer le dump planifié + copie hors hôte + test de restauration ; journaliser montant/comptes des transactions ; corriger les écarts de R5 (dédoublonnage, expiration de la deny-list) |
| **90 jours** | Registre des tiers et plans de sortie ; MFA ; SIEM avec rétention ; PITR ; ré-entraînement du modèle sur trafic réel ; tests de restauration trimestriels |
| **180 jours et plus** | Programme annuel de tests de résilience documenté ; cadrage TLPT ; formation des dirigeants ; revue indépendante |

## 4. Matrice de preuve : où vérifier

| Affirmation | Comment la vérifier | Statut |
|---|---|---|
| Les 4 scénarios respectent le contrat Red/Blue | `python -m pytest attacks/tests -q` (4 tests verts au 2026-10-19) | [R] |
| Le WAF produit les événements et la métrique de blocage | `python -m pytest security/waf/tests -q` (5 tests verts) | [R] |
| Aucun secret en clair, pas de socket Docker brut, pas de conteneur privilégié, pas de clé age dans le dépôt | `security/hardening/audit.sh` ; `gitleaks detect --source .` | script [R] ; exécution sur `infra/` après livraison [S] |
| Détection : seuil, taux, version | `ml/training/artifacts/v1.0.0/baseline_stats.json` (`threshold`, `evaluation`) ; hash du modèle contrôlé au chargement | [R] |
| La table de décision sépare disponibilité et intégrité | `remediation/decision.py` (invariants) ; tests unitaires à écrire (`remediation/tests/` vide) | code [R], tests [S] |
| MTTD/MTTR par incident | `resilience_mttd_seconds`, `resilience_mttr_seconds` (20 derniers incidents), journal `incidents.db`, Loki `remediation_verified` | [M] en recette |
| Reprise de bout en bout (avant / attaque / détection / remédiation / après) | `make demo` (`scripts/demo.sh`), `scripts/verify_tx` code 0 | [S] |

**Lecture pour le jury** : ce document ne revendique **aucune conformité** NIS2 ou DORA. Il établit (1) quelles exigences un prototype de 4 jours peut **prouver**, avec la preuve et sa limite ; (2) celles qu'il **ne peut pas** prouver ; (3) les arbitrages recommandés à une direction, chacun appuyé sur un élément du démonstrateur que l'on peut vérifier.
