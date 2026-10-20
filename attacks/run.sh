#!/usr/bin/env bash
# Lanceur de scénarios de test de résilience — RESILIENCE-ALPHA.
# Génère un signal observable borné contre la stack DU PROJET uniquement.
# Intensité et durée PLAFONNÉES ; arrêt automatique ; kill-switch.
#
# Deux familles :
#   - Scénarios-contrat (scenarios/*.yml) : service_flood, auth_abuse, web_attack, data_corruption
#   - Techniques avancées (sans yml, décrites dans attacks/ATTACKS.md) :
#     rotation, pulse, recon, replay, slow — chacune éprouve une facette de la défense.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCENARIO_DIR="${ROOT}/attacks/scenarios"
RUNLOG="${ROOT}/attacks/.runlog"
PIDFILE="${ROOT}/attacks/.run.pid"

TECHNIQUES="rotation pulse recon replay slow"

usage() {
  echo "Usage : run.sh <scenario|technique> [--target URL] [--duration S] [--rate N]"
  echo "        run.sh --stop        # kill-switch"
  echo "Scénarios : $(ls "${SCENARIO_DIR}" 2>/dev/null | sed 's/\.yml//' | tr '\n' ' ')"
  echo "Techniques : ${TECHNIQUES}"
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
is_technique() { echo " ${TECHNIQUES} " | grep -q " ${SCENARIO} "; }
if [[ ! -f "${SCENARIO_FILE}" ]] && ! is_technique; then
  echo "Inconnu : ${SCENARIO}"; usage; exit 1
fi

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

# Garde de périmètre : la cible DOIT appartenir au réseau du projet (CLAUDE.md : « pas d'action
# offensive hors du réseau du projet »). Surchargeable via ATTACK_ALLOWED_HOSTS (liste d'hôtes
# séparés par des espaces) pour un autre banc d'essai interne. Hors liste -> refus (fail closed).
ALLOWED_HOSTS="${ATTACK_ALLOWED_HOSTS:-192.168.137.1 127.0.0.1 localhost waf}"
ALLOWED_HOSTS="${ALLOWED_HOSTS//,/ }"   # tolère la virgule comme séparateur (cf. console)
target_host="${TARGET#*://}"      # retire le schéma
target_host="${target_host%%/*}"  # retire le chemin
target_host="${target_host%%:*}"  # retire le port
# -F : comparaison littérale (les points de l'IP ne doivent pas être pris pour des métacaractères).
if ! printf ' %s ' ${ALLOWED_HOSTS} | grep -qF " ${target_host} "; then
  echo "Cible hors périmètre projet : ${target_host} (autorisés : ${ALLOWED_HOSTS} ; cf. ATTACK_ALLOWED_HOSTS)" >&2
  exit 2
fi

echo "$(date -Iseconds) START ${SCENARIO} target=${TARGET} duration=${DURATION}s rate=${RATE}/s" | tee -a "${RUNLOG}"
: > "${PIDFILE}"

bounded_loop() {
  # Boucle bornée : envoie des requêtes jusqu'à la fin de la fenêtre, puis s'arrête seule.
  # Débit tenu par LOTS d'une seconde : un seul `curl --parallel` envoie RATE requêtes, puis on
  # attend la seconde suivante. Un curl par requête plafonnait vers 5-8 req/s sous Git Bash
  # (~100 ms de lancement + TLS chacun) : le « flood » se confondait avec le trafic normal.
  local path="$1" method="${2:-GET}" body="${3:-}" token="${4:-}"
  local end=$(( $(date +%s) + DURATION ))
  local auth=()
  [[ -n "${token}" ]] && auth=(-H "Authorization: Bearer ${token}")
  if curl --help all 2>/dev/null | grep -q -- '--parallel '; then
    local urls=() i
    for (( i = 0; i < RATE; i++ )); do urls+=("${TARGET}${path}"); done
    local data=()
    [[ "${method}" == "POST" ]] && data=(-X POST -H 'Content-Type: application/json' -d "${body}")
    # Chaque lot part en tâche de fond : un lot de 40 met ~0,9 s (40 poignées de main TLS), l'attendre
    # avant le suivant diviserait le débit par deux. --max-time 5 borne les lots simultanés à ~5.
    local now
    while now=$(date +%s); (( now < end )); do
      curl -k -s --parallel --parallel-max "${RATE}" --max-time 5 \
        ${auth[@]+"${auth[@]}"} ${data[@]+"${data[@]}"} "${urls[@]}" >/dev/null 2>&1 &
      while (( $(date +%s) == now )); do sleep 0.05; done   # lot suivant à la seconde suivante
    done
    wait
    return
  fi
  # Repli (curl < 7.66, sans --parallel) : une requête à la fois, débit réel plus faible.
  local interval; interval=$(awk "BEGIN{print 1/${RATE}}")
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

rand_ip() { printf '%d.%d.%d.%d' $((RANDOM%223+1)) $((RANDOM%256)) $((RANDOM%256)) $((RANDOM%256)); }

rotation_loop() {
  # service_flood dont la SOURCE change à chaque requête (X-Forwarded-For + User-Agent).
  # Éprouve la remédiation par blocage d'IP : tient-elle quand la source tourne ?
  local uas=("curl/8" "Mozilla/5.0" "python-requests/2" "Go-http-client/1.1" "RedTeam/triade")
  local end=$(( $(date +%s) + DURATION ))
  local interval; interval=$(awk "BEGIN{print 1/${RATE}}")
  while (( $(date +%s) < end )); do
    curl -k -s -o /dev/null -X POST -H 'Content-Type: application/json' \
      -H "X-Forwarded-For: $(rand_ip)" -H "User-Agent: ${uas[$((RANDOM%${#uas[@]}))]}" \
      -d '{"dst_account":"FR-FAKE-0002","amount_cents":100}' "${TARGET}/api/v1/transactions" || true
    sleep "${interval}"
  done
}

pulse_loop() {
  # Rafales ON/OFF au lieu d'un flot plat : éprouve les seuils temporels (rate[1m]).
  local on="${PULSE_ON:-3}" off="${PULSE_OFF:-4}"
  local end=$(( $(date +%s) + DURATION ))
  local interval; interval=$(awk "BEGIN{print 1/${RATE}}")
  while (( $(date +%s) < end )); do
    local bend=$(( $(date +%s) + on ))
    while (( $(date +%s) < bend && $(date +%s) < end )); do
      curl -k -s -o /dev/null -X POST -H 'Content-Type: application/json' \
        -d '{"dst_account":"FR-FAKE-0002","amount_cents":100}' "${TARGET}/api/v1/transactions" || true
      sleep "${interval}"
    done
    echo "$(date -Iseconds) pulse: silence ${off}s" >> "${RUNLOG}"
    sleep "${off}"
  done
}

recon_sweep() {
  # Énumération légère d'endpoints (404) : éprouve la LARGEUR de détection (recon -> unknown).
  local paths=(/admin /.env /.git/config /backup.zip /api/v1/users /phpmyadmin \
               /api/v1/accounts/999999 /wp-login.php /actuator/health /server-status)
  local end=$(( $(date +%s) + DURATION ))
  local interval; interval=$(awk "BEGIN{print 1/${RATE}}")
  local i=0
  while (( $(date +%s) < end )); do
    curl -k -s -o /dev/null "${TARGET}${paths[$((i%${#paths[@]}))]}" || true
    i=$((i+1)); sleep "${interval}"
  done
}

replay_loop() {
  # Rejoue la MÊME transaction (request_id figé) : éprouve la déduplication (intégrité).
  local body='{"dst_account":"FR-FAKE-0002","amount_cents":100,"request_id":"REPLAY-FIXED-0001"}'
  local end=$(( $(date +%s) + DURATION ))
  local interval; interval=$(awk "BEGIN{print 1/${RATE}}")
  while (( $(date +%s) < end )); do
    curl -k -s -o /dev/null -X POST -H 'Content-Type: application/json' \
      -H 'Idempotency-Key: REPLAY-FIXED-0001' -d "${body}" "${TARGET}/api/v1/transactions" || true
    sleep "${interval}"
  done
}

slow_conn() {
  # Saturation par CONNEXIONS LENTES (approximation Slowloris, bornée) : éprouve les
  # timeouts / le pool de connexions. Nombre de connexions plafonné, maintenues DURATION s.
  local n="${SLOW_CONN:-40}"; (( n > 60 )) && n=60
  echo "$(date -Iseconds) slow: ${n} connexions lentes maintenues ${DURATION}s" >> "${RUNLOG}"
  local j
  for (( j=0; j<n; j++ )); do
    curl -k -s -o /dev/null --max-time "${DURATION}" --limit-rate 1 "${TARGET}/api/v1/accounts" &
    echo $! >> "${PIDFILE}"
  done
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
  rotation) rotation_loop & echo $! >> "${PIDFILE}" ;;
  pulse)    pulse_loop    & echo $! >> "${PIDFILE}" ;;
  recon)    recon_sweep   & echo $! >> "${PIDFILE}" ;;
  replay)   replay_loop   & echo $! >> "${PIDFILE}" ;;
  slow)     slow_conn ;;   # spawn ses propres connexions (pids dans PIDFILE)
  data_corruption)
    # La base est sur le réseau interne `data` : ce scénario se déclenche côté OPÉRATEUR
    # (PC Hôte), pas depuis le PC Attaquant. Procédure réversible, données fictives.
    echo "Scénario data_corruption : à déclencher depuis le PC Hôte (base non exposée)."
    echo "  1) backup sain   : ansible-playbook infra/ansible/playbooks/pg_backup.yml"
    echo "  2) corruption    : ansible-playbook infra/ansible/playbooks/db_corrupt_fake.yml"
    echo "  -> verify_tx passe KO ; la remédiation restore_pg_dump doit rétablir l'état."
    echo "  annulation manuelle : ansible-playbook infra/ansible/playbooks/db_corrupt_fake.yml -e mode=revert"
    exit 0 ;;
  *)
    echo "Pas de générateur pour ${SCENARIO}"; exit 1 ;;
esac

# Attend la fin de la fenêtre bornée puis nettoie.
wait || true
rm -f "${PIDFILE}"
echo "$(date -Iseconds) END ${SCENARIO}" | tee -a "${RUNLOG}"
