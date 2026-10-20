#!/usr/bin/env bash
# demo.sh — joue les 5 temps de la démo Zero-Touch Recovery, enchaînés d'une commande.
# Conçu pour être filmable en <= 60 s sans coupure (Clip Chrono).
# La remédiation est AUTONOME : ce script ne corrige rien, il observe et prouve.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# Identifiants du jeu fictif (SEED_PASSWORD) : .env produit par `make decrypt`.
if [[ -f "${ROOT}/.env" ]]; then set -a; . "${ROOT}/.env"; set +a; fi
SCENARIO="${1:-service_flood}"
TARGET="${TARGET:-https://192.168.137.1}"

step() { printf '\n\033[1;36m== %s ==\033[0m\n' "$1"; }

step "1/5 AVANT — le service fonctionne"
BASE_URL="${TARGET}" "${ROOT}/scripts/verify_tx" || { echo "Démo impossible : état initial KO"; exit 1; }

step "2/5 ATTAQUE — scénario ${SCENARIO} (depuis le PC Attaquant en démo notée)"
"${ROOT}/attacks/run.sh" "${SCENARIO}" --target "${TARGET}" --duration 20 --rate 50 &
ATTACK_PID=$!

step "3/5 DÉTECTION — le modèle ML relève l'anomalie"
echo "Observer anomaly_score sur le dashboard / Grafana (resilience_anomaly_score)."
echo "Le détecteur émet un AnomalyEvent vers le moteur de remédiation."

step "4/5 REMÉDIATION — action automatique (aucune intervention humaine)"
echo "Le moteur applique la table de décision (blocage IP / redémarrage / restauration)."
echo "Suivre la timeline et le MTTD/MTTR sur le dashboard."

step "5/5 APRÈS — vérification automatique du retour à la normale"
# Laisse la boucle de remédiation agir, puis re-vérifie (la remédiation le fait aussi d'elle-même).
for i in $(seq 1 12); do
  sleep 5
  if BASE_URL="${TARGET}" "${ROOT}/scripts/verify_tx" >/dev/null 2>&1; then
    echo "Service rétabli — transaction fictive de nouveau réussie."
    break
  fi
  echo "  ... reprise en cours (${i}/12)"
done

wait "${ATTACK_PID}" 2>/dev/null || true
step "FIN — voir MTTR affiché sur le dashboard"
