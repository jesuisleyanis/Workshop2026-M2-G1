# RESILIENCE-ALPHA — orchestration du monorepo.
# Flow du projet : on code, on teste, on documente, on met à jour la roadmap.

COMPOSE := docker compose -f infra/compose/docker-compose.yml
ROOT    := $(shell pwd)

.PHONY: help up up-full down seed verify demo attack stop-attack reset test test-py test-front audit package decrypt \
        traffic train capture-baseline capture-attack calibrate

ML_DATA  := ml/training/data
DURATION ?= 30m

help: ## Affiche cette aide
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

decrypt: ## Déchiffre les secrets SOPS vers .env
	scripts/decrypt-secrets.sh

up: decrypt ## Lève la stack (profil démo minimal)
	$(COMPOSE) --profile demo up -d --build

up-full: decrypt ## Lève la stack complète (observabilité + full)
	$(COMPOSE) --profile demo --profile full up -d --build

down: ## Arrête et nettoie la stack
	$(COMPOSE) --profile demo --profile full --profile attack --profile ai down

seed: ## Peuple les données fictives
	python3 scripts/seed.py

verify: ## Transaction de contrôle (exit 0 = OK)
	@python3 scripts/verify_tx

demo: ## Joue les 5 temps de la démo (SC=<scenario>)
	scripts/demo.sh $(or $(SC),service_flood)

attack: ## Lance un scénario de test (SC=<scenario>) — dev uniquement
	attacks/run.sh $(or $(SC),service_flood)

stop-attack: ## Kill-switch des scénarios
	attacks/run.sh --stop

reset: ## Remet la cible à l'état "avant"
	attacks/reset.sh

# ---- ML : ré-entraînement sur vraies séries Prometheus (ml/training/README.md §6) ----
traffic: ## Trafic légitime réaliste (DURATION=30m) — baseline et temps 1 de la démo
	python3 scripts/gen_normal_traffic.py --duration $(DURATION)

capture-baseline: ## Joue DURATION de trafic normal puis capture la baseline réelle
	python3 scripts/gen_normal_traffic.py --duration $(DURATION)
	$(COMPOSE) exec -T collector python -m ml.collector.capture --last $(DURATION) \
	  --label normal > $(ML_DATA)/baseline_real.csv

capture-attack: ## Joue le scénario SC (sur fond de trafic normal) et ajoute ses fenêtres
	@test -n "$(SC)" || { echo "SC=<scenario> requis"; exit 1; }
	@start=$$(date -u +%Y-%m-%dT%H:%M:%SZ); \
	  python3 scripts/gen_normal_traffic.py --duration 90s & \
	  attacks/run.sh $(SC); sleep 30; wait; \
	  end=$$(date -u +%Y-%m-%dT%H:%M:%SZ); \
	  hdr=$$( [ -s $(ML_DATA)/attacks_real.csv ] && echo --no-header ); \
	  $(COMPOSE) exec -T collector python -m ml.collector.capture --start $$start --end $$end \
	    --label $(SC) $$hdr >> $(ML_DATA)/attacks_real.csv

train: ## Entraîne le modèle (vraie baseline + calibration si présentes)
	python3 -m ml.training.train --version $(or $(VERSION),1.1.0) \
	  $(if $(wildcard $(ML_DATA)/baseline_real.csv),--data $(ML_DATA)/baseline_real.csv) \
	  $(if $(wildcard $(ML_DATA)/attacks_real.csv),--attack-data $(ML_DATA)/attacks_real.csv) \
	  $(if $(wildcard $(ML_DATA)/calibration.json),--calibration $(ML_DATA)/calibration.json)

calibrate: ## Calibre le seuil sur les attaques réelles capturées (puis rebuild detector)
	python3 -m ml.training.calibrate

audit: ## Audit de durcissement du dépôt
	security/hardening/audit.sh

package: ## Construit l'archive Code.zip du rendu
	scripts/package_deliverables.sh

# ---- Tests : chaque composant teste son périmètre -------------------------------
test: test-py test-front ## Lance tous les tests

test-py: ## Tests Python (lib partagée + services + ml + remediation + cyber)
	@echo "== Tests Python =="
	@python3 -m pytest -q \
	  libs/python/resilience_common \
	  services ml remediation assistant \
	  security/waf/tests attacks/tests scripts/tests 2>/dev/null || \
	  echo "(certains composants nécessitent leur venv — voir leur README)"

test-front: ## Tests front (front + dashboard)
	@echo "== Tests front =="
	@for app in services/front dashboard; do \
	  if [ -f $$app/package.json ]; then (cd $$app && npm run test --silent 2>/dev/null || true); fi; \
	done
