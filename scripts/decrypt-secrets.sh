#!/usr/bin/env bash
# Déchiffre les secrets SOPS vers un .env local non commité, au lancement de la stack.
# Prérequis : sops + age installés, clé privée age présente (SOPS_AGE_KEY_FILE).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENC="${ROOT}/security/sops/secrets.enc.env"
OUT="${ROOT}/.env"

: "${SOPS_AGE_KEY_FILE:=${HOME}/.config/sops/age/keys.txt}"
export SOPS_AGE_KEY_FILE

if [[ ! -f "${ENC}" ]]; then
  echo "ERREUR : ${ENC} introuvable. Chiffrez d'abord secrets.example.env -> secrets.enc.env (voir security/sops/README.md)." >&2
  exit 1
fi
if [[ ! -f "${SOPS_AGE_KEY_FILE}" ]]; then
  echo "ERREUR : clé age privée absente (${SOPS_AGE_KEY_FILE}). Elle n'est jamais commitée ; récupérez-la auprès de l'équipe." >&2
  exit 1
fi

# umask 077 : le fichier déchiffré est créé d'emblée en 0600 (pas de fenêtre lisible par autrui).
(umask 077; sops --decrypt "${ENC}" > "${OUT}")
chmod 600 "${OUT}"
echo "Secrets déchiffrés vers ${OUT} (non commité)."

# Complète .env avec les secrets locaux du back-office facial absents de SOPS (générés une fois).
# Appelé via bash : ne dépend pas du bit exécutable (checkout Windows, core.fileMode=false).
bash "${ROOT}/scripts/ensure-local-secrets.sh" "${ROOT}"
