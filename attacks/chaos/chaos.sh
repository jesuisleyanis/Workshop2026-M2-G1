#!/usr/bin/env bash
# Chaos engineering — injection de PANNES NON-ATTAQUE, côté opérateur (PC Hôte).
# But : prouver que la plateforme se rétablit d'une panne qui n'est PAS une attaque
# (crash de processus, gel momentané), grâce à sa résilience intrinsèque
# (restart policy `unless-stopped`, healthchecks) — distinct de la chaîne
# attaque -> détection ML -> remédiation (voir attacks/README.md).
#
# Garde-fous : cible UNIQUEMENT les conteneurs du projet `resilience-g1` ; pannes
# BORNÉES et RÉVERSIBLES (jamais de suppression de conteneur/volume, jamais de perte
# de données) ; arrêt automatique ; kill-switch (`--stop`) ; journal horodaté.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RUNLOG="${ROOT}/attacks/.runlog"
PIDFILE="${ROOT}/attacks/.chaos.pid"

PROJECT="${COMPOSE_PROJECT:-resilience-g1}"   # préfixe des conteneurs (compose name:)
ALLOWED_SERVICES="payment-api auth front"     # liste blanche : jamais la DB, les secrets, l'obs

usage() {
  echo "Usage : chaos.sh <fault> [--service S] [--duration S]"
  echo "        chaos.sh --stop        # kill-switch (unpause + nettoyage)"
  echo "Pannes : crash  (docker kill -> la restart policy relance)"
  echo "         freeze (docker pause N s -> unpause automatique)"
  echo "Services autorisés : ${ALLOWED_SERVICES}"
}

container_for() {
  local svc="$1"
  echo "${PROJECT}-${svc}-1"
}

stop_all() {
  # Dé-gèle tout conteneur du projet resté en pause, puis nettoie.
  if command -v docker >/dev/null 2>&1; then
    for svc in ${ALLOWED_SERVICES}; do
      local c; c="$(container_for "${svc}")"
      if [[ "$(docker inspect -f '{{.State.Paused}}' "${c}" 2>/dev/null || echo false)" == "true" ]]; then
        docker unpause "${c}" >/dev/null 2>&1 || true
        echo "$(date -Iseconds) CHAOS unpause ${c}" | tee -a "${RUNLOG}"
      fi
    done
  fi
  rm -f "${PIDFILE}"
  echo "$(date -Iseconds) KILL-SWITCH chaos : état rétabli" | tee -a "${RUNLOG}"
}

[[ $# -ge 1 ]] || { usage; exit 1; }
if [[ "$1" == "--stop" ]]; then stop_all; exit 0; fi

FAULT="$1"; shift
SERVICE="payment-api"
DURATION=15
while [[ $# -gt 0 ]]; do
  case "$1" in
    --service)  SERVICE="$2"; shift 2 ;;
    --duration) DURATION="$2"; shift 2 ;;
    *) echo "Option inconnue : $1"; usage; exit 1 ;;
  esac
done

# Garde-fous.
command -v docker >/dev/null 2>&1 || { echo "docker introuvable — chaos à lancer sur le PC Hôte"; exit 1; }
echo " ${ALLOWED_SERVICES} " | grep -q " ${SERVICE} " || { echo "Service non autorisé : ${SERVICE}"; usage; exit 1; }
(( DURATION > 30 )) && DURATION=30     # plafond de sécurité

CONTAINER="$(container_for "${SERVICE}")"
docker inspect "${CONTAINER}" >/dev/null 2>&1 || { echo "Conteneur absent : ${CONTAINER} (stack up ?)"; exit 1; }

echo "$(date -Iseconds) CHAOS START ${FAULT} service=${SERVICE} container=${CONTAINER} duration=${DURATION}s" | tee -a "${RUNLOG}"
: > "${PIDFILE}"

case "${FAULT}" in
  crash)
    # Crash brutal : le processus meurt. La restart policy `unless-stopped` doit
    # relancer le conteneur ; healthcheck + verify_tx confirment la reprise.
    docker kill "${CONTAINER}" >/dev/null
    echo "$(date -Iseconds) CHAOS killed ${CONTAINER} (attente reprise par la restart policy)" | tee -a "${RUNLOG}" ;;
  freeze)
    # Gel momentané : SIGSTOP via docker pause, puis unpause automatique après la fenêtre.
    # Entièrement réversible, aucune donnée perdue.
    docker pause "${CONTAINER}" >/dev/null
    ( sleep "${DURATION}"; docker unpause "${CONTAINER}" >/dev/null 2>&1 || true
      echo "$(date -Iseconds) CHAOS unpause ${CONTAINER}" | tee -a "${RUNLOG}" ) &
    echo $! >> "${PIDFILE}"
    wait || true ;;
  *)
    echo "Panne inconnue : ${FAULT}"; usage; exit 1 ;;
esac

rm -f "${PIDFILE}"
echo "$(date -Iseconds) CHAOS END ${FAULT} ${CONTAINER}" | tee -a "${RUNLOG}"
