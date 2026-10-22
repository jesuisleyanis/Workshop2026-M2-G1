# Plan — détection rapide (< 5 s) et corrections de la chaîne de reprise

Statut (2026-10-21) : lots 0, 1, 2, 4, 5, 6 **appliqués** sur `perf/lancement-stack` ; lot 3 (captures + recalibration)
en cours. Suivi et preuves : `ROADMAP.md` § Détection rapide.

Écarts au plan trouvés pendant la mise en œuvre :
- Lot 1 : l'IP source est résolue par le **detector** (déjà sur `obs`, accès Loki) et non par la remédiation ; la
  remédiation rejoint quand même `obs`, sans quoi `confirm_waf_block` (lecture Loki prévue par son CDC) ne marchait pas.
- Trafic normal et flood utilisaient des mots de passe en dur périmés : baseline v1.1 polluée de 401 (corrigé).
- `data_corruption` n'avait jamais été capturé (pas de déclencheur sans Ansible) : `attacks/db_corrupt_local.sh`.
- Captures : Alertmanager suspendu avec le detector (ses actions tronqueraient les fenêtres d'attaque).
Chaque lot suit la Definition of Done : code → tests → doc → ligne `ROADMAP.md`.
Contexte : [`plan-optimisation-lancement.md`](plan-optimisation-lancement.md) (lancement), [`commandes.md`](commandes.md).

---

## 1. Où passe le temps aujourd'hui

Chaîne mesurée dans la configuration (pas encore chronométrée de bout en bout : c'est le lot 0) :

| Maillon | Réglage actuel | Latence ajoutée (pire cas) |
|---|---|---|
| Scrape Prometheus des services | `scrape_interval: 10s` | jusqu'à 10 s |
| Fenêtre des features | `rate(...[30s])` (`PROM_RATE_WINDOW`) | montée progressive du signal (dilué sur 30 s) |
| Collector | relève toutes les `COLLECT_INTERVAL_SECONDS=15` | jusqu'à 15 s |
| Detector | relève le collector toutes les `POLL_INTERVAL_SECONDS=15`, **non synchronisé** | jusqu'à 15 s |
| Modèle + POST remédiation | ~10 ms + 1 aller-retour HTTP | négligeable |
| **Total attaque → AnomalyEvent** | | **~20 s typique, ~40 s pire cas** (estimation) |

La calibration actuelle le confirme côté modèle : `mttd_s_worst = 15 s` pour chaque scénario
(`ml/training/data/calibration.json`), sans compter scrape ni décalage collector/detector.

**Objectif** : attaque → `AnomalyEvent` posté en **p95 ≤ 5 s** (vs ~20–40 s), mesuré par le banc du lot 0, **sans faux
positif** sur 60 min de trafic normal, et en gardant la décision au **modèle ML** (R8 : pas de `if` codé en dur).

Budget visé :

| Maillon | Cible | Latence |
|---|---|---|
| Scrape payment-api / auth / waf-exporter | 1 s | ≤ 1 s |
| Fenêtre des features | `rate[5s]` (5 échantillons) | signal visible dès 1–2 échantillons |
| Collector | 1 s | ≤ 1 s |
| Collector → detector | **push** (flux SSE) au lieu d'un polling | ~0 s |
| Confirmation (anti faux positif) | 2 fenêtres consécutives au-dessus du seuil | +1 s |
| **Total** | | **~3–5 s** |

---

## 2. Constats à corriger

| # | Constat | Gravité | Preuve |
|---|---|---|---|
| D1 | **L'AnomalyEvent du detector ne porte jamais `source_ip`** → `waf_block_ip` / `waf_blacklist_ip` échouent (`aucune IP source dans l'événement`) : sur le chemin ML, l'attaquant n'est **jamais bloqué** (flood : seul le redémarrage s'applique ; auth_abuse : seul le rate-limit) | **Critique démo** | `ml/detector/events.py:build_event`, `remediation/actions/waf.py:42` |
| D2 | Calibration fragile : 1 seul passage par scénario ; marge étroite (normal max 0,692 · seuil 0,717 · plus faible pic d'attaque 0,746) | Élevée | `calibration.json` |
| D3 | Latence de détection ~20–40 s (§1) | Élevée (demande) | config |
| D4 | auth : `httpx` absent des dépendances runtime → conteneur en boucle | **Corrigé, non commité** | `infra/tests/test_runtime_requirements.py` |
| D5 | WAF : scripts d'entrypoint 93/96 de l'image de base (tag republié) → WAF en boucle | **Corrigé, non commité** | test `test_entrypoint_scripts_…` |
| D6 | Tag de base WAF `4.25.2-nginx-alpine-lts` republié en amont : la reproductibilité (R5) n'est pas garantie par un tag | Moyenne | incident D5 |
| D7 | Rotation de secrets non gérée : volume Postgres et comptes `demo01/02` gardent les anciens mots de passe ; `make seed` (idempotent) ne les réaligne pas | Moyenne | incident du 21/10 |
| D8 | `check-env` ne vérifie que l'existence de `.env`, pas qu'il contient toutes les clés (`.env` périmé à 4/8 clés passé inaperçu) | Moyenne | incident du 21/10 |
| D9 | Grafana en boucle : conflit de versions des règles provisionnées dans le volume `grafana-data` | Moyenne | logs Grafana |
| D10 | `make seed` / `make verify` appellent `python3`, absent sous Windows | Faible | Makefile |
| D11 | Mosquitto publié sur `0.0.0.0:1883` au lieu de l'IP du hotspot (tests rouges sur `main`) | Moyenne (exposition) | `test_mosquitto_…` |
| D12 | Tests de `services/face-id` hors de `make test` | Faible | `test_makefile.py` |
| D13 | Chemin SOC lent : `rate[1m]` + `for: 30s` + `group_wait: 5s` | Faible (chemin secondaire) | `infra/prometheus/rules/soc.yml` |

---

## 3. Lots

### Lot 0 — Banc de mesure de la latence de détection (prérequis, 2 h)
Sans mesure, « plus rapide » n'est pas prouvable devant le jury.
- `scripts/bench_detection.py` : pour chaque scénario × N passages (défaut 5), noter `t0` = départ de
  `attacks/run.sh`, puis interroger le journal du moteur (`GET /incidents`, via le conteneur) ou `/api/v1/status` du
  detector jusqu'au premier incident postérieur à `t0` ; sortie : tableau p50/p95/max par scénario + taux de détection.
- Rejouer aussi 10 min de trafic normal : nombre de faux positifs.
- Mesure **avant** toute modification = référence du dossier.
- Tests : unitaires du calcul (horloges simulées, incident absent, timeout).

### Lot 1 — Corrections bloquantes de la chaîne (P0)
**1a. IP source (D1).** Résolution côté **remédiation**, au moment d'agir, quand `source: from_event` et que l'événement
n'a pas d'IP : requête Loki sur les logs JSON du WAF (`client_ip` y est déjà) sur la fenêtre de l'anomalie
(`ts - 30 s` → maintenant), filtre par type (flood : toutes requêtes ; auth_abuse : `/api/v1/login` en 401/429 ;
web_attack : 403), `topk` par nombre de lignes.
- Garde-fous : IP retenue seulement si elle pèse ≥ 60 % des lignes filtrées ; validation `ipaddress` ; `never_block_ips`
  appliqué ; sinon `ActionError` explicite → l'action suivante s'exécute (comportement actuel).
- IP résolue écrite dans le journal et la timeline (preuve).
- Pourquoi côté remédiation : contrat `AnomalyEvent` inchangé, couvre aussi le chemin Alertmanager sans label.
  Variante : enrichir l'événement dans le detector (change `docs/contracts.md §3`) — à trancher en équipe.
- Tests : Loki simulé (IP dominante, pas de dominante, IP protégée, Loki injoignable) ; e2e flood → IP présente dans
  `blocked_ips.conf`.

**1b. Commiter D4 + D5** (déjà testés).

**1c. Épingler la base WAF par digest (D6)** : `FROM owasp/modsecurity-crs:4.25.2-nginx-alpine-lts@sha256:…` ; test
statique « FROM tiers épinglé par digest ».

### Lot 2 — Pipeline rapide (P0, objet de la demande)
| Changement | Fichier |
|---|---|
| Scrape **1 s** pour `payment-api`, `auth`, `waf-exporter` ; `cadvisor` reste à 5 s (coûteux, CPU/RAM ne sont pas les signaux qui détectent le plus tôt) | `infra/prometheus/prometheus.yml` |
| `PROM_RATE_WINDOW=5s`, `COLLECT_INTERVAL_SECONDS=1` (env du collector) ; `stale_after` = 3 s | compose, `ml/collector` |
| **Flux collector → detector** : `GET /features/stream` (SSE, un message par snapshot, numéro de séquence) ; le detector s'y abonne, repli sur polling 1 s si le flux tombe | `ml/collector/app.py`, `ml/detector/app.py` |
| **Confirmation par le modèle** : anomalie si `score ≥ seuil` sur **2 fenêtres consécutives**, ou `score ≥ seuil_haut` sur une seule ; les deux seuils viennent de la calibration (aucun seuil métier en dur) | `ml/detector/core.py`, `ml/training/calibrate.py` |
| `EVENT_COOLDOWN_SECONDS` inchangé (60 s) : un seul événement par incident | — |

- Tests : collector (snapshot par seconde, séquence monotone, client lent), detector (consommation du flux, reconnexion,
  repli polling, confirmation 2/2, seuil haut), contrat de config (`window ≥ 4 × scrape` des jobs utilisés par les
  features, intervalles cohérents entre compose et collector).
- Coût : 3 cibles × 1 scrape/s, négligeable pour Prometheus ; volume TSDB ×10 sur ces séries (rétention courte suffit).

### Lot 3 — Ré-entraînement sur la nouvelle définition des fenêtres (P0, indissociable du lot 2)
Changer la fenêtre change ce que mesurent les features : **l'ancien modèle et sa calibration deviennent invalides**
(le garde-fou d'empreinte fera d'ailleurs échouer le build si on l'oublie).
1. `make capture-baseline` (60 min à 1 s = ~3 600 fenêtres ; `MIN_ROWS` relevé en conséquence), avec variations de
   débit (`--rps`) pour couvrir le normal « chargé ».
2. `make capture-attack` **× 3 passages par scénario** (D2), dont variantes douces (`rate` bas, `pulse`, `slow`) pour
   ne pas calibrer sur des attaques trop franches.
3. `make calibrate` avec `--max-mttd 3` (nouvelle variable `CALIBRATE_ARGS` du Makefile) : seuil, seuil haut, MTTD
   modèle par scénario ; `guardrail_z` recalculé.
4. `make train` puis `make retrain-detector`.
- Critères d'acceptation (banc du lot 0) : 0 faux positif sur 60 min de normal rejoué ; 100 % des passages détectés ;
  **p95 attaque → événement ≤ 5 s** ; écart normal max / seuil documenté.
- Doc : `ml/training/README.md` §4–6 (résultats), `docs/contracts.md §2` (fenêtre 5 s / pas 1 s).

### Lot 4 — Exploitation et reproductibilité (P1)
- **D7** `make seed RESET_PASSWORDS=1` : réaligne les comptes fictifs sur `SEED_PASSWORD` ; procédure documentée de
  rotation du mot de passe Postgres (`ALTER USER` via le socket local, sans détruire le volume).
- **D8** `check-env` compare les clés de `.env` à `security/sops/secrets.example.env` et liste les manquantes.
- **D9** `make reset-grafana` (supprime uniquement `grafana-data` : tout est reprovisionné depuis le dépôt) + note dans
  `infra/grafana/provisioning/alerting/README-SOC.md`.
- **D10** `seed`/`verify`/`traffic` passent par `$(PYTHON)`, détection auto `python3` → `python`.
- `make down` avec `--remove-orphans` (évite les conflits de réseau avec une ancienne stack).
- Tests : statiques Makefile ; unitaire du diff de clés `.env`.

### Lot 5 — Dette de tests et exposition (P1)
- **D11** Mosquitto : `ports: ["${MQTT_BIND_IP:-192.168.137.1}:1883:1883"]` → tests verts.
- **D12** `services/face-id` ajouté à `PY_COMPONENTS`.

### Lot 6 — Chemin SOC plus réactif (P2)
- **D13** Règles SOC : `rate[30s]`, `for: 10s`, `evaluation_interval: 5s` ; Alertmanager `group_wait: 1s`.
  Reste un filet de sécurité, plus lent que le ML par construction. Tests : `infra/tests/test_soc_rules.py` à adapter.

---

## 4. Ordre, effort, dépendances

| Lot | Priorité | Effort | Dépend de |
|---|---|---|---|
| 0 Banc de mesure | P0 | 2 h | stack levée |
| 1 IP source + commits + digest | **P0** | 3 h | — |
| 2 Pipeline rapide | **P0** | 4 h | 0 (mesure avant) |
| 3 Ré-entraînement | **P0** | 2 h de travail + ~1 h 30 de captures | 2 |
| 4 Exploitation | P1 | 2 h | — |
| 5 Tests / Mosquitto | P1 | 30 min | — |
| 6 SOC | P2 | 1 h | — |

Lots indépendants pouvant avancer en parallèle : **1**, **4**, **5** (fichiers disjoints). **2 → 3** sont séquentiels
et passent après la mesure de référence du lot 0.

## 5. Risques

| Risque | Parade |
|---|---|
| Fenêtre de 5 s plus bruitée → faux positifs | confirmation 2 fenêtres ; baseline longue et variée ; critère 0 FP au banc |
| Attaque lente (`slow`) invisible en 5 s | elle reste détectée par la dérive des fenêtres suivantes ; mesurée à part au banc, limite documentée si besoin |
| Capture trop courte → modèle instable | `MIN_ROWS` relevé ; held-out chronologique conservé |
| Blocage d'une IP légitime (NAT, même poste en dev) | seuil de dominance 60 %, `never_block_ips`, `ATTACK_TARGET` distinct en dev |
| Charge CPU sur le portable 16 Go | cadvisor laissé à 5 s ; mesurer `cpu_pct_max` de Prometheus au banc |
