#!/usr/bin/env bash
# Lanceur de scénarios de test de résilience — RESILIENCE-ALPHA.
# Génère un signal observable borné contre la stack DU PROJET uniquement.
# Intensité et durée PLAFONNÉES par le scénario ; arrêt automatique ; kill-switch.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCENARIO_DIR="${ROOT}/attacks/scenarios"
RUNLOG="${RUNLOG:-${ROOT}/attacks/.runlog}"
PIDFILE="${PIDFILE:-${ROOT}/attacks/.run.pid}"

usage() {
  echo "Usage : run.sh <scenario> [--target URL] [--duration S] [--rate N]"
  echo "        run.sh --stop        # kill-switch"
  echo "Scénarios : $(ls "${SCENARIO_DIR}" 2>/dev/null | sed 's/\.yml//' | tr '\n' ' ')"
}

stop_all() {
  if [[ -f "${PIDFILE}" ]]; then
    while read -r pid; do kill "${pid}" 2>/dev/null || true; done < "${PIDFILE}"
    rm -f "${PIDFILE}"
    echo "$(date -Iseconds) KILL-SWITCH : scénarios arrêtés" | tee -a "${RUNLOG}"
  else
    echo "Aucun scénario en cours."
  fi
}

[[ $# -ge 1 ]] || { usage; exit 1; }
if [[ "$1" == "--stop" ]]; then stop_all; exit 0; fi

SCENARIO="$1"; shift
SCENARIO_FILE="${SCENARIO_DIR}/${SCENARIO}.yml"
[[ -f "${SCENARIO_FILE}" ]] || { echo "Scénario inconnu : ${SCENARIO}"; usage; exit 1; }

TARGET="https://192.168.137.1"
DURATION=20
RATE=40
while [[ $# -gt 0 ]]; do
  case "$1" in
    --target)   TARGET="$2"; shift 2 ;;
    --duration) DURATION="$2"; shift 2 ;;
    --rate)     RATE="$2"; shift 2 ;;
    *) echo "Option inconnue : $1"; usage; exit 1 ;;
  esac
done

# Plafonds de sécurité (le banc d'essai ne doit jamais dépasser ces bornes).
(( DURATION > 60 )) && DURATION=60
(( RATE > 100 )) && RATE=100

echo "$(date -Iseconds) START ${SCENARIO} target=${TARGET} duration=${DURATION}s rate=${RATE}/s" | tee -a "${RUNLOG}"
: > "${PIDFILE}"

bounded_loop() {
  # Boucle bornée : envoie des requêtes jusqu'à la fin de la fenêtre, puis s'arrête seule.
  local path="$1" method="${2:-GET}" body="${3:-}" token="${4:-}"
  local end=$(( $(date +%s) + DURATION ))
  local interval; interval=$(awk "BEGIN{print 1/${RATE}}")
  local auth=()
  [[ -n "${token}" ]] && auth=(-H "Authorization: Bearer ${token}")
  while (( $(date +%s) < end )); do
    if [[ "${method}" == "POST" ]]; then
      curl -k -s -o /dev/null -X POST -H 'Content-Type: application/json' ${auth[@]+"${auth[@]}"} \
        -d "${body}" "${TARGET}${path}" || true
    else
      curl -k -s -o /dev/null "${TARGET}${path}" || true
    fi
    sleep "${interval}"
  done
}

# Session d'un client fictif (comptes de scripts/seed.py) : jeton puis id du 1er compte.
# Pas de jq sur le PC Attaquant : extraction par motif, suffisante pour ces réponses plates.
login_token() {
  curl -k -s -X POST -H 'Content-Type: application/json' \
    -d "{\"username\":\"$1\",\"password\":\"$2\"}" "${TARGET}/api/v1/login" \
    | sed -n 's/.*"access_token" *: *"\([^"]*\)".*/\1/p' || true
}
first_account_id() {
  curl -k -s -H "Authorization: Bearer $1" "${TARGET}/api/v1/accounts" \
    | grep -o '"id" *: *[0-9]*' | head -n 1 | grep -o '[0-9]*$' || true
}

case "${SCENARIO}" in
  service_flood)
    # Le flood doit atteindre la DB : jeton valide et ids de compte ENTIERS (contrat
    # payment-api, StrictInt). Sans eux il ne produit que des 401/422 rejetés avant
    # Postgres, une signature fausse pour le ML. 1 centime : le solde tient tout le flood.
    TOKEN="$(login_token "${FLOOD_USER:-demo01}" "${FLOOD_PASSWORD:-demo-pass-01}")"
    SRC_ID="$( [[ -n "${TOKEN}" ]] && first_account_id "${TOKEN}" || true)"
    DST_ID="${FLOOD_DST_ID:-$(first_account_id "$(login_token "${FLOOD_DST_USER:-demo02}" "${FLOOD_DST_PASSWORD:-demo-pass-02}")")}"
    if [[ -z "${SRC_ID}" || -z "${DST_ID}" ]]; then
      echo "service_flood : login ou lecture des comptes impossible sur ${TARGET} (make seed ?)" | tee -a "${RUNLOG}"
      rm -f "${PIDFILE}"; exit 1
    fi
    bounded_loop "/api/v1/transactions" POST \
      "{\"src_account\":${SRC_ID},\"dst_account\":${DST_ID},\"amount_cents\":1}" "${TOKEN}" &
    echo $! >> "${PIDFILE}" ;;
  auth_abuse)
    bounded_loop "/api/v1/login" POST '{"username":"demo01","password":"wrong-password"}' &
    echo $! >> "${PIDFILE}" ;;
  web_attack)
    # Charges CRS standards de test — déclenchent les règles OWASP, pas d'exploitation réelle.
    bounded_loop "/api/v1/accounts?id=1%27%20OR%20%271%27%3D%271" GET &
    echo $! >> "${PIDFILE}"
    bounded_loop "/../../etc/passwd" GET &
    echo $! >> "${PIDFILE}" ;;
  data_corruption)
    echo "Scénario data_corruption : exécuter la procédure d'altération réversible de données fictives" \
         "documentée dans scenarios/data_corruption.yml (via playbook Ansible dédié)." ;;
  *)
    echo "Pas de générateur pour ${SCENARIO}"; exit 1 ;;
esac

# Attend la fin de la fenêtre bornée puis nettoie.
wait || true
rm -f "${PIDFILE}"
echo "$(date -Iseconds) END ${SCENARIO}" | tee -a "${RUNLOG}"
