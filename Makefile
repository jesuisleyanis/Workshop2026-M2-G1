# RESILIENCE-ALPHA — orchestration du monorepo.
# Flow du projet : on code, on teste, on documente, on met à jour la roadmap.

SHELL := /bin/bash   # pipefail dans les recettes de tests
COMPOSE := docker compose -f infra/compose/docker-compose.yml
ROOT    := $(shell pwd)
# Charge .env (produit par `make decrypt`) dans l'environnement d'une cible : SEED_PASSWORD, tokens...
LOADENV := set -a; [ -f .env ] && . ./.env; set +a;

.PHONY: help up up-full down seed verify demo attack stop-attack reset test test-py test-front audit package decrypt model

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

# Apps Vitest. Le back-office exige Node >= 22.15 (ou 24) : jsdom embarque une version d'undici
# qui ne se charge pas sur Node 20 — vérifier `node --version` avant `make test-front`.
FRONT_APPS := services/front services/backoffice dashboard

test-front: ## Tests front (front + back-office + dashboard ; Node >= 22.15)
	@echo "== Tests front (node $$(node --version 2>/dev/null || echo absent)) =="
	@rc=0; \
	for app in $(FRONT_APPS); do \
	  if [ -f $$app/package.json ]; then (cd $$app && npm run test --silent) || rc=1; fi; \
	done; \
	[ $$rc -eq 0 ] || { echo "== Tests front : ÉCHEC"; exit 1; }; \
	echo "== Tests front : OK"
