# RESILIENCE-ALPHA — orchestration du monorepo.
# Flow du projet : on code, on teste, on documente, on met à jour la roadmap.

SHELL := /bin/bash   # pipefail dans les recettes de tests
COMPOSE := docker compose -f infra/compose/docker-compose.yml
ROOT    := $(shell pwd)
# Charge .env (produit par `make decrypt`) dans l'environnement d'une cible : SEED_PASSWORD, tokens...
LOADENV := set -a; [ -f .env ] && . ./.env; set +a;

.PHONY: help up up-full down seed verify demo attack stop-attack reset test test-py test-front audit package decrypt model \
        traffic train capture-baseline capture-attack calibrate ml-tools test-ml

ML_DATA  := ml/training/data
# Baseline : 60 min = 240 fenêtres de 15 s (minimum MIN_ROWS = ml.training.dataset.MIN_TRAINING_ROWS)
DURATION ?= 60m
MIN_ROWS := 200
# Durée d'un scénario (attacks/run.sh --duration, max 60) ; RATE_LAG = PROM_RATE_WINDOW,
# délai avant que les rate() retombent après l'attaque
ATTACK_S ?= 20
RATE_LAG := 30
VERSION  ?= 1.1.0
ML_TOOLS := resilience/ml-tools
ML_SRC   := $(shell pwd -W 2>/dev/null || pwd)
ML_DOCKER = MSYS_NO_PATHCONV=1 docker run --rm -v "$(ML_SRC):/src"
TRAIN_DATA_ARGS = $(if $(wildcard $(ML_DATA)/baseline_real.csv),--data $(ML_DATA)/baseline_real.csv) \
  $(if $(wildcard $(ML_DATA)/attacks_real.csv),--attack-data $(ML_DATA)/attacks_real.csv)

help: ## Affiche cette aide
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

decrypt: ## Déchiffre les secrets SOPS vers .env
	scripts/decrypt-secrets.sh

model: ## Entraîne le modèle ML si l'artefact est absent (requis avant le build du detector)
	@if [ -f ml/training/artifacts/model.joblib ] && [ -f ml/training/artifacts/baseline_stats.json ]; then \
	  echo "== Modèle présent (ml/training/artifacts/) — pas de ré-entraînement =="; \
	else \
	  echo "== Entraînement du modèle (python -m ml.training.train) =="; \
	  $(PYTHON) -m ml.training.train; \
	fi

up: decrypt model ## Lève la stack (profil démo minimal)
	$(COMPOSE) --profile demo up -d --build

up-full: decrypt model ## Lève la stack complète (observabilité + full)
	$(COMPOSE) --profile demo --profile full up -d --build

down: ## Arrête et nettoie la stack
	$(COMPOSE) --profile demo --profile full --profile attack --profile ai down

seed: ## Peuple les données fictives (resilience_db.seed, via le conteneur payment-api)
	@$(LOADENV) python3 scripts/seed.py

verify: ## Transaction de contrôle (exit 0 = OK)
	@$(LOADENV) python3 scripts/verify_tx

demo: ## Joue les 5 temps de la démo (SC=<scenario>)
	@$(LOADENV) scripts/demo.sh $(or $(SC),service_flood)

attack: ## Lance un scénario de test (SC=<scenario>) — dev uniquement
	attacks/run.sh $(or $(SC),service_flood)

stop-attack: ## Kill-switch des scénarios
	attacks/run.sh --stop

reset: ## Remet la cible à l'état "avant"
	attacks/reset.sh

# ---- ML : ré-entraînement sur vraies séries Prometheus (ml/training/README.md §6) ----
traffic: ## Trafic légitime réaliste (DURATION=60m) — baseline et temps 1 de la démo
	python3 scripts/gen_normal_traffic.py --duration $(DURATION)

# Les captures écrivent dans un .tmp et ne remplacent/complètent le CSV que si elles ont
# réussi : un échec ne détruit jamais une capture précédente.
capture-baseline: ## Joue DURATION (60m) de trafic normal puis capture la baseline réelle
	python3 scripts/gen_normal_traffic.py --duration $(DURATION)
	$(COMPOSE) exec -T collector python -m ml.collector.capture --last $(DURATION) \
	  --label normal > $(ML_DATA)/baseline_real.csv.tmp
	@rows=$$(( $$(wc -l < $(ML_DATA)/baseline_real.csv.tmp) - 1 )); \
	  if [ $$rows -lt $(MIN_ROWS) ]; then \
	    echo "capture: $$rows fenêtres < $(MIN_ROWS) requises (DURATION trop courte ?) — baseline inchangée"; \
	    rm -f $(ML_DATA)/baseline_real.csv.tmp; exit 1; fi; \
	  mv $(ML_DATA)/baseline_real.csv.tmp $(ML_DATA)/baseline_real.csv; \
	  echo "baseline : $$rows fenêtres -> $(ML_DATA)/baseline_real.csv"

# Fenêtre étiquetée = durée de l'attaque + RATE_LAG s (le temps que les rate() retombent),
# pas les 90 s de trafic de fond : sinon le detection_rate réel serait dilué.
capture-attack: ## Joue le scénario SC (ATTACK_S s, sur fond de trafic normal) et ajoute ses fenêtres
	@test -n "$(SC)" || { echo "SC=<scenario> requis"; exit 1; }
	@start_s=$$(date -u +%s); \
	  python3 scripts/gen_normal_traffic.py --duration 90s & \
	  attacks/run.sh $(SC) --duration $(ATTACK_S); sleep $(RATE_LAG); wait; \
	  end_s=$$(( start_s + $(ATTACK_S) + $(RATE_LAG) )); \
	  $(COMPOSE) exec -T collector python -m ml.collector.capture \
	    --start $$(date -u -d @$$start_s +%Y-%m-%dT%H:%M:%SZ) \
	    --end $$(date -u -d @$$end_s +%Y-%m-%dT%H:%M:%SZ) \
	    --label $(SC) > $(ML_DATA)/attacks_real.csv.tmp || { rm -f $(ML_DATA)/attacks_real.csv.tmp; exit 1; }; \
	  if [ -s $(ML_DATA)/attacks_real.csv ]; then \
	    tail -n +2 $(ML_DATA)/attacks_real.csv.tmp >> $(ML_DATA)/attacks_real.csv; \
	    rm -f $(ML_DATA)/attacks_real.csv.tmp; \
	  else mv $(ML_DATA)/attacks_real.csv.tmp $(ML_DATA)/attacks_real.csv; fi; \
	  echo "$(SC) ajouté à $(ML_DATA)/attacks_real.csv"

# train / calibrate / test-ml tournent dans l'image `ml-tools` (étape du Dockerfile detector) :
# même Python 3.12 et même scikit-learn que le build du detector. Le modèle calibré est donc
# exactement celui que le build ré-entraîne (model_fingerprint identique) — et rien à
# installer sur le poste. `pwd -W` + MSYS_NO_PATHCONV : chemins Docker corrects sous Git Bash.
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
	$(ML_DOCKER) -w /src $(ML_TOOLS) python -m ml.training.calibrate

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
PYTHON ?= python3
# Composants testés DEPUIS leur répertoire (config pytest locale, imports relatifs à la racine du composant).
PY_COMPONENTS := libs/python/resilience_common libs/python/resilience_db \
                 services/auth services/payment-api ml remediation assistant
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
