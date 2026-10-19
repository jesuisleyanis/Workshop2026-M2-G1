#!/usr/bin/env bash
# Opération Triade — campagne Red Team MULTI-ÉTAPES corrélée (banc d'essai RESILIENCE-ALPHA).
# Enchaîne, de façon décalée, 3 vagues bornées pour éprouver la corrélation SOC et la
# remédiation de plusieurs incidents SUCCESSIFS — pas pour maximiser des dégâts.
#
# Chaque vague délègue à run.sh (qui applique les PLAFONDS : rate ≤ 100/s, duration ≤ 60 s)
# et reste donc dans le périmètre : cible = le WAF du projet, données fictives, réversible.
# Kill-switch : campaign.sh --stop (arrête la vague en cours via run.sh --stop).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN="${ROOT}/attacks/run.sh"
RUNLOG="${ROOT}/attacks/.runlog"

usage() {
  echo "Usage : campaign.sh [--target URL] [--gap S]"
  echo "        campaign.sh --stop     # kill-switch (stoppe la vague en cours)"
}

if [[ "${1:-}" == "--stop" ]]; then
  bash "${RUN}" --stop || true
  echo "$(date -Iseconds) CAMPAIGN KILL-SWITCH" | tee -a "${RUNLOG}"
  exit 0
fi

TARGET="https://192.168.137.1"
GAP=6
while [[ $# -gt 0 ]]; do
  case "$1" in
    --target) TARGET="$2"; shift 2 ;;
    --gap)    GAP="$2";    shift 2 ;;
    *) echo "Option inconnue : $1"; usage; exit 1 ;;
  esac
done
(( GAP > 15 )) && GAP=15

# Vagues : <scénario> <durée> <débit> — toutes bornées, run.sh re-plafonne par sécurité.
STAGES=(
  "auth_abuse 15 40"     # 1. Feinte : rafale 401, attire l'alerte SOC
  "web_attack 12 20"     # 2. Sonde  : motifs CRS contre le WAF
  "service_flood 20 60"  # 3. Assaut : le vrai coup sur payment-api
)

echo "$(date -Iseconds) CAMPAIGN START Operation-Triade target=${TARGET} stages=${#STAGES[@]}" | tee -a "${RUNLOG}"
i=0
for stage in "${STAGES[@]}"; do
  i=$((i+1))
  read -r scn dur rate <<< "${stage}"
  echo "$(date -Iseconds) CAMPAIGN vague ${i}/${#STAGES[@]} : ${scn} (${dur}s @ ${rate}/s)" | tee -a "${RUNLOG}"
  bash "${RUN}" "${scn}" --target "${TARGET}" --duration "${dur}" --rate "${rate}"
  if (( i < ${#STAGES[@]} )); then
    echo "$(date -Iseconds) CAMPAIGN pause ${GAP}s" | tee -a "${RUNLOG}"
    sleep "${GAP}"
  fi
done
echo "$(date -Iseconds) CAMPAIGN END Operation-Triade" | tee -a "${RUNLOG}"
