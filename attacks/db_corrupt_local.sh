#!/usr/bin/env bash
# Déclencheur LOCAL du scénario data_corruption (PC Hôte), sans Ansible — même opération que
# infra/ansible/playbooks/db_corrupt_fake.yml : renommage RÉVERSIBLE de la table fictive
# `transactions` (aucun DROP, aucune perte), pendant une fenêtre bornée, puis rétablissement
# GARANTI (trap : fin normale, erreur ou Ctrl-C). Sert aux captures ML (`make capture-attack
# SC=data_corruption`) : sans lui, la capture étiquetterait du trafic normal comme une attaque.
#
#   attacks/db_corrupt_local.sh --duration 20      # corrompt 20 s puis rétablit
#   attacks/db_corrupt_local.sh --revert           # rétablit seulement (idempotent)
set -euo pipefail

DB_CONTAINER="${DB_CONTAINER:-resilience-g1-postgres-1}"
DB_NAME="resilience"          # garde-fou : uniquement la base fictive
DB_USER="resilience"
LIVE="transactions"
QUARANTINE="transactions__corrupted"
DURATION=20

sql() {
  MSYS_NO_PATHCONV=1 docker exec -i "${DB_CONTAINER}" \
    psql -v ON_ERROR_STOP=1 -q -U "${DB_USER}" -d "${DB_NAME}" -c "$1"
}
revert() { sql "ALTER TABLE IF EXISTS ${QUARANTINE} RENAME TO ${LIVE};" && echo "data_corruption : table ${LIVE} rétablie"; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --duration) DURATION="$2"; shift 2 ;;
    --revert)   revert; exit 0 ;;
    *) echo "Option inconnue : $1" >&2; exit 1 ;;
  esac
done
(( DURATION > 60 )) && DURATION=60   # même plafond que attacks/run.sh

trap revert EXIT
trap 'exit 130' INT TERM
sql "ALTER TABLE IF EXISTS ${LIVE} RENAME TO ${QUARANTINE};"
echo "data_corruption : table ${LIVE} écartée pour ${DURATION} s (réversible)"
sleep "${DURATION}"
