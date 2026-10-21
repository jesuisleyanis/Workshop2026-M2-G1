# RESILIENCE-ALPHA — orchestration du monorepo.
# Flow du projet : on code, on teste, on documente, on met à jour la roadmap.

SHELL := /bin/bash   # pipefail dans les recettes de tests
# --env-file .env : Compose chercherait sinon le .env dans infra/compose/ (répertoire du fichier
# compose), où il n'existe pas -> POSTGRES_PASSWORD, JWT_SECRET, tokens vides. Affectation récursive
# (`=`) : le wildcard est évalué à l'exécution de la recette, donc APRÈS `make decrypt`.
COMPOSE = docker compose -f infra/compose/docker-compose.yml $(if $(wildcard .env),--env-file .env)
ROOT    := $(shell pwd)
# Charge .env (produit par `make decrypt`) dans l'environnement d'une cible : SEED_PASSWORD, tokens...
LOADENV := set -a; [ -f .env ] && . ./.env; set +a;
# Interpréteur hôte des scripts stdlib (seed, verify_tx, trafic, banc) : `python3` sous Linux/macOS,
# `python` sous Windows (où `python3` n'est souvent qu'un raccourci vers le Microsoft Store).
PY_HOST ?= $(shell python3 -c "" >/dev/null 2>&1 && echo python3 || echo python)

# Profils Compose (infra/compose/docker-compose.yml). `demo` = services sans profil (chemin critique) ;
# `ml` = collector + detector : SANS lui, aucune détection, donc pas de Zero-Touch Recovery.
PROFILES_DEMO := --profile demo --profile ml
PROFILES_FULL := $(PROFILES_DEMO) --profile full
PROFILES_ALL  := $(PROFILES_FULL) --profile iot --profile attack --profile ai

.PHONY: help up up-full up-iot build start start-full ui ps down reset-grafana check-env seed verify demo attack stop-attack reset \
        test test-py test-front audit package decrypt model retrain-detector bench \
        traffic train capture-baseline capture-attack capture-remote calibrate ml-tools test-ml

ML_DATA  := ml/training/data
# Baseline : 60 min = 3 600 fenêtres d'1 s (COLLECT_INTERVAL_SECONDS du collector) ; MIN_ROWS = 50 min
DURATION ?= 60m
MIN_ROWS := 3000
# Durée d'un scénario (attacks/run.sh --duration, max 60) ; RATE_LAG = PROM_RATE_WINDOW,
# délai avant que les rate() retombent après l'attaque
ATTACK_S ?= 20
# Cible des captures d'attaque : le WAF vu depuis CE poste. `attacks/run.sh` vise par défaut
# https://192.168.137.1 (IP du hotspot, pour le PC attaquant de la démo) : sur le poste qui héberge
# la stack, cette adresse n'existe que si le hotspot est actif, et sinon l'attaque ne produit aucun
# signal alors que ses fenêtres seraient étiquetées « attaque ».
ATTACK_TARGET ?= https://localhost
RATE_LAG := 10
# data_corruption se déclenche côté PC Hôte (base non exposée) : renommage réversible de la table.
ATTACK_CMD = $(if $(filter data_corruption,$(SC)),attacks/db_corrupt_local.sh --duration $(ATTACK_S),attacks/run.sh $(SC) --target $(ATTACK_TARGET) --duration $(ATTACK_S))
VERSION  ?= 1.2.0
# Budget MTTD côté modèle depuis le début de la capture (pas de 1 s, confirmation 4 fenêtres) ; voir ml.training.calibrate --help
CALIBRATE_ARGS ?= --max-mttd 10 --confirm 4
ML_TOOLS := resilience/ml-tools
ML_SRC   := $(shell pwd -W 2>/dev/null || pwd)
ML_DOCKER = MSYS_NO_PATHCONV=1 docker run --rm -v "$(ML_SRC):/src"
TRAIN_DATA_ARGS = $(if $(wildcard $(ML_DATA)/baseline_real.csv),--data $(ML_DATA)/baseline_real.csv) \
  $(if $(wildcard $(ML_DATA)/attacks_real.csv),--attack-data $(ML_DATA)/attacks_real.csv)

help: ## Affiche cette aide
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

decrypt: ## Déchiffre les secrets SOPS vers .env
	scripts/decrypt-secrets.sh

# Aperçu local uniquement : `up` n'en dépend PAS, le build du detector entraîne lui-même le modèle
# (étape `trainer` de ml/detector/Dockerfile). Tourne dans l'image ml-tools : aucun sklearn sur le poste.
model: ml-tools ## Entraîne le modèle dans ml/training/artifacts/ s'il est absent (aperçu, facultatif)
	@if [ -f ml/training/artifacts/model.joblib ] && [ -f ml/training/artifacts/baseline_stats.json ]; then \
	  echo "== Modèle présent (ml/training/artifacts/) — pas de ré-entraînement =="; \
	else \
	  echo "== Entraînement du modèle (image $(ML_TOOLS)) =="; \
	  $(ML_DOCKER) -w /src $(ML_TOOLS) python -m ml.training.train --version $(VERSION) $(TRAIN_DATA_ARGS); \
	fi

check-env: ## Vérifie que .env existe et contient toutes les clés de secrets.example.env
	@[ -f .env ] || { echo "ERREUR : .env absent — lancer \`make decrypt\` (clé age requise, voir security/sops/README.md)."; exit 1; }
	@missing=$$(grep -oE '^[A-Z][A-Z0-9_]*=' security/sops/secrets.example.env | tr -d = | while read -r key; do \
	  grep -qE "^$$key=" .env || printf '%s ' "$$key"; done); \
	[ -z "$$missing" ] || { echo "ERREUR : .env incomplet (déchiffrement ancien ?) — clés absentes : $$missing"; \
	  echo "  -> les ajouter à security/sops/secrets.enc.env (sops) puis make decrypt"; exit 1; }

up: decrypt check-env ## Construit et lève la stack démo (chemin critique + détection ML)
	$(COMPOSE) $(PROFILES_DEMO) up -d --build

up-full: decrypt check-env ## Construit et lève la stack complète (démo + ML + observabilité full)
	$(COMPOSE) $(PROFILES_FULL) up -d --build

up-iot: decrypt check-env ## Construit et lève la stack démo + broker MQTT sur le point d'accès
	$(COMPOSE) $(PROFILES_DEMO) --profile iot up -d --build

build: check-env ## Construit les images (démo + ML + full) sans rien lancer
	$(COMPOSE) $(PROFILES_FULL) build

start: check-env ## Relance la stack démo SANS rebuild (images déjà construites)
	$(COMPOSE) $(PROFILES_DEMO) up -d

start-full: check-env ## Relance la stack complète SANS rebuild
	$(COMPOSE) $(PROFILES_FULL) up -d

# Supervision locale : dashboard publié sur le loopback du PC hôte uniquement (surcouche Compose).
UI_COMPOSE = $(COMPOSE) -f infra/compose/docker-compose.ui-local.yml
ui: check-env ## Ouvre le dashboard sur http://127.0.0.1:8081 (PC hôte seulement, jamais sur le hotspot)
	$(UI_COMPOSE) $(PROFILES_FULL) up -d dashboard
	@echo "Dashboard : http://127.0.0.1:8081"

ps: ## État des conteneurs (tous profils)
	$(COMPOSE) $(PROFILES_ALL) ps

down: ## Arrête et nettoie la stack (tous profils, conteneurs orphelins d'une ancienne version compris)
	$(COMPOSE) $(PROFILES_ALL) down --remove-orphans

# Grafana garde des versions des règles provisionnées dans son volume ; un conflit le fait boucler
# (« UNIQUE constraint failed: alert_rule_version »). Rien d'irremplaçable dans ce volume :
# sources de données, règles SOC et mot de passe admin sont reprovisionnés depuis le dépôt et .env.
reset-grafana: check-env ## Réinitialise l'état interne de Grafana (volume grafana-data) puis le relance
	$(COMPOSE) $(PROFILES_ALL) rm -sf grafana
	docker volume rm -f resilience-g1_grafana-data
	$(COMPOSE) $(PROFILES_FULL) up -d grafana

# Le build du detector ré-entraîne le modèle avec ml/training/data/{baseline_real.csv,calibration.json}.
retrain-detector: check-env ## Reconstruit le detector (ré-entraînement au build) et le relance seul
	$(COMPOSE) $(PROFILES_DEMO) build detector
	$(COMPOSE) $(PROFILES_DEMO) up -d --no-deps detector

seed: ## Peuple les données fictives (RESET_PASSWORDS=1 : réaligne les comptes existants sur SEED_PASSWORD)
	@$(LOADENV) SEED_RESET_PASSWORDS=$(if $(RESET_PASSWORDS),1,0) $(PY_HOST) scripts/seed.py

verify: ## Transaction de contrôle (exit 0 = OK)
	@$(LOADENV) $(PY_HOST) scripts/verify_tx

demo: ## Joue les 5 temps de la démo (SC=<scenario>)
	@$(LOADENV) scripts/demo.sh $(or $(SC),service_flood)

bench: ## Banc de latence attaque -> détection -> action (BENCH_ARGS="--runs 5 --quiet 600")
	@$(LOADENV) $(PY_HOST) scripts/bench_detection.py $(BENCH_ARGS)

attack: ## Lance un scénario de test (SC=<scenario>) — dev uniquement
	@$(LOADENV) attacks/run.sh $(or $(SC),service_flood)

stop-attack: ## Kill-switch des scénarios
	attacks/run.sh --stop

reset: ## Remet la cible à l'état "avant"
	attacks/reset.sh

# ---- ML : ré-entraînement sur vraies séries Prometheus (ml/training/README.md §6) ----
traffic: ## Trafic légitime réaliste (DURATION=60m) — baseline et temps 1 de la démo
	@$(LOADENV) $(PY_HOST) scripts/gen_normal_traffic.py --duration $(DURATION)

# Pendant une capture, le detector est ARRÊTÉ puis relancé quoi qu'il arrive (succès, échec,
# Ctrl-C) : sinon l'ancien modèle déclencherait des remédiations (redémarrages, limites,
# blocage d'IP) qui pollueraient la baseline « normale », et en dev waf_deny_ip bloquerait
# aussi le trafic de fond (même IP que l'attaque). Alertmanager (chemin SOC, règles à 10 s) est
# suspendu de même : ses actions (blocage d'IP, restauration de dump) tronqueraient les fenêtres
# d'attaque capturées. Les deux sont relancés en fin de capture, quoi qu'il arrive.
# Les captures écrivent dans un .tmp et ne remplacent/complètent le CSV que si elles ont
# réussi : un échec ne détruit jamais une capture précédente.
DETECTOR_OFF = echo "detector + alertmanager suspendus pendant la capture"; $(COMPOSE) $(PROFILES_FULL) stop detector alertmanager >/dev/null;   trap 'rm -f $(ML_DATA)/*.csv.tmp; $(COMPOSE) $(PROFILES_FULL) start detector alertmanager >/dev/null; echo "detector + alertmanager relancés"' EXIT;   trap 'exit 130' INT TERM

capture-baseline: ## Joue DURATION (60m) de trafic normal puis capture la baseline réelle (detector arrêté)
	@set -e; $(LOADENV) $(DETECTOR_OFF); 	  $(PY_HOST) scripts/gen_normal_traffic.py --duration $(DURATION); 	  $(COMPOSE) exec -T collector python -m ml.collector.capture --last $(DURATION) 	    --label normal > $(ML_DATA)/baseline_real.csv.tmp; 	  rows=$$(( $$(wc -l < $(ML_DATA)/baseline_real.csv.tmp) - 1 )); 	  if [ $$rows -lt $(MIN_ROWS) ]; then 	    echo "capture: $$rows fenêtres < $(MIN_ROWS) requises (DURATION trop courte ?) — baseline inchangée"; 	    exit 1; fi; 	  mv $(ML_DATA)/baseline_real.csv.tmp $(ML_DATA)/baseline_real.csv; 	  echo "baseline : $$rows fenêtres -> $(ML_DATA)/baseline_real.csv"

# Fenêtre étiquetée = durée de l'attaque + RATE_LAG s (le temps que les rate() retombent),
# pas les 90 s de trafic de fond : sinon le detection_rate réel serait dilué.
capture-attack: ## Joue le scénario SC (ATTACK_S s, sur fond de trafic normal) et ajoute ses fenêtres (detector arrêté)
	@test -n "$(SC)" || { echo "SC=<scenario> requis"; exit 1; }
	@set -e; $(LOADENV) $(DETECTOR_OFF); 	  start_s=$$(date -u +%s); 	  $(PY_HOST) scripts/gen_normal_traffic.py --duration 90s & 	  $(ATTACK_CMD); sleep $(RATE_LAG); wait; 	  end_s=$$(( start_s + $(ATTACK_S) + $(RATE_LAG) )); 	  $(COMPOSE) exec -T collector python -m ml.collector.capture 	    --start $$(date -u -d @$$start_s +%Y-%m-%dT%H:%M:%SZ) 	    --end $$(date -u -d @$$end_s +%Y-%m-%dT%H:%M:%SZ) 	    --label $(SC) > $(ML_DATA)/attacks_real.csv.tmp; 	  if [ -s $(ML_DATA)/attacks_real.csv ]; then 	    tail -n +2 $(ML_DATA)/attacks_real.csv.tmp >> $(ML_DATA)/attacks_real.csv; 	  else cp $(ML_DATA)/attacks_real.csv.tmp $(ML_DATA)/attacks_real.csv; fi; 	  echo "$(SC) ajouté à $(ML_DATA)/attacks_real.csv"

# train / calibrate / test-ml tournent dans l'image `ml-tools` (étape du Dockerfile detector) :
# même Python 3.12 et même scikit-learn que le build du detector. Le modèle calibré est donc
# exactement celui que le build ré-entraîne (model_fingerprint identique) — et rien à
# installer sur le poste. `pwd -W` + MSYS_NO_PATHCONV : chemins Docker corrects sous Git Bash.
# Calibration sur les VRAIES attaques de la démo : à lancer sur le PC HÔTE (celui que vise le PC
# attaquant), le modèle devant apprendre le normal ET les attaques de cette machine-là. Même capture que
# capture-attack, mais l'attaque part du PC attaquant pendant la fenêtre annoncée (rien n'est lancé ici).
REMOTE_S ?= 30
capture-remote: ## Capture une attaque lancée depuis le PC attaquant (SC=<scenario>, fenêtre REMOTE_S=30 s)
	@test -n "$(SC)" || { echo "SC=<scenario> requis"; exit 1; }
	@$(MAKE) --no-print-directory capture-attack SC=$(SC) ATTACK_S=$(REMOTE_S) 	  ATTACK_CMD='echo ">>> Lancez MAINTENANT $(SC) depuis le PC attaquant (fenêtre de $(REMOTE_S) s)"; sleep $(REMOTE_S)'

ml-tools: ## Construit l'image d'outils ML (Python + scikit-learn du runtime)
	docker build -f ml/detector/Dockerfile --target ml-tools -t $(ML_TOOLS) .

train: ml-tools ## Entraîne le modèle (vraie baseline + calibration si présentes)
	$(ML_DOCKER) -w /src $(ML_TOOLS) python -m ml.training.train --version $(VERSION) \
	  $(TRAIN_DATA_ARGS) \
	  $(if $(wildcard $(ML_DATA)/calibration.json),--calibration $(ML_DATA)/calibration.json)

# Calibre le modèle qu'il vient lui-même d'entraîner SANS calibration (sinon une
# calibration périmée ferait échouer l'entraînement nécessaire à la recalibrer).
calibrate: ml-tools ## Ré-entraîne sur la baseline puis calibre le seuil sur les attaques réelles
	$(ML_DOCKER) -w /src $(ML_TOOLS) python -m ml.training.train --version $(VERSION) $(TRAIN_DATA_ARGS)
	$(ML_DOCKER) -w /src $(ML_TOOLS) python -m ml.training.calibrate $(CALIBRATE_ARGS)

test-ml: ml-tools ## Tests ML (pytest) dans l'image d'outils, Python 3.12
	$(ML_DOCKER) -w /src/ml $(ML_TOOLS) python -m pytest -p no:cacheprovider

audit: ## Audit de durcissement du dépôt
	security/hardening/audit.sh

package: ## Construit l'archive Code.zip du rendu
	scripts/package_deliverables.sh

# ---- Tests : chaque composant teste son périmètre -------------------------------
# Un process pytest PAR composant (ticket #19) : les services déclarent chacun leurs métriques
# Prometheus au niveau module ; les importer dans un seul process lève `DuplicateTimeseries`.
# Chaque composant a sa propre config pytest (pytest.ini / pyproject) et ses dépendances :
# `PYTHON` doit pointer sur un interpréteur où elles sont installées (voir README racine, § Tests).
PYTHON ?= $(PY_HOST)
# Composants testés DEPUIS leur répertoire (config pytest locale, imports relatifs à la racine du composant).
PY_COMPONENTS := libs/python/resilience_common libs/python/resilience_db \
                 services/auth services/payment-api services/face-id ml remediation assistant
# Répertoires de tests "plats" (contrats statiques), lancés depuis la racine du dépôt.
PY_TEST_DIRS  := security/waf/tests attacks/tests scripts/tests infra/tests tests/e2e

test: test-py test-front ## Lance tous les tests

test-py: ## Tests Python, un process pytest par composant (échec si l'un d'eux échoue)
	@echo "== Tests Python ($(PYTHON)) =="
	@set -o pipefail; rc=0; \
	for c in $(PY_COMPONENTS); do \
	  printf '%-34s ' "$$c"; \
	  (cd $$c && $(PYTHON) -m pytest -q -p no:cacheprovider 2>&1 | tail -1) || rc=1; \
	done; \
	for d in $(PY_TEST_DIRS); do \
	  printf '%-34s ' "$$d"; \
	  ($(PYTHON) -m pytest -q -p no:cacheprovider $$d 2>&1 | tail -1) || rc=1; \
	done; \
	[ $$rc -eq 0 ] || { echo "== Tests Python : ÉCHEC (voir ci-dessus ; dépendances : README § Tests)"; exit 1; }; \
	echo "== Tests Python : OK"

test-front: ## Tests front (front + dashboard)
	@echo "== Tests front =="
	@rc=0; \
	for app in services/front dashboard; do \
	  if [ -f $$app/package.json ]; then (cd $$app && npm run test --silent) || rc=1; fi; \
	done; \
	[ $$rc -eq 0 ] || { echo "== Tests front : ÉCHEC"; exit 1; }; \
	echo "== Tests front : OK"
