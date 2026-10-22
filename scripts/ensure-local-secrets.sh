#!/usr/bin/env bash
# Complète le .env déchiffré avec les secrets du back-office facial absents de SOPS.
#
# FACE_INTERNAL_TOKEN, FACE_DATA_KEY et BACKOFFICE_BOOTSTRAP_TOKEN sont propres au PC Hôte :
# s'ils ne sont pas (encore) dans security/sops/secrets.enc.env, ils sont générés UNE fois
# dans .env.local (0600, non commité) puis recopiés dans .env à chaque `make decrypt`.
# FACE_DATA_KEY doit rester stable : la perdre rend les enrôlements illisibles (réenrôlement).
# Une valeur présente dans SOPS l'emporte toujours sur .env.local.
set -euo pipefail

ROOT="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
ENV_FILE="${ROOT}/.env"
LOCAL_FILE="${ROOT}/.env.local"

rand_b64_32() {
  if command -v openssl >/dev/null 2>&1; then openssl rand -base64 32
  else python3 -c 'import base64,os;print(base64.b64encode(os.urandom(32)).decode())'; fi
}
rand_hex() {
  if command -v openssl >/dev/null 2>&1; then openssl rand -hex "$1"
  else python3 -c "import secrets;print(secrets.token_hex($1))"; fi
}
value_of() {  # value_of KEY FILE -> valeur (vide si absente)
  [[ -f "$2" ]] || return 0
  sed -n "s/^$1=//p" "$2" | tail -n 1 | sed -e "s/^['\"]//" -e "s/['\"]$//"
}

touch "${ENV_FILE}"
(umask 077; touch "${LOCAL_FILE}")
chmod 600 "${LOCAL_FILE}"

generated=0
for key in FACE_INTERNAL_TOKEN FACE_DATA_KEY BACKOFFICE_BOOTSTRAP_TOKEN; do
  [[ -n "$(value_of "${key}" "${ENV_FILE}")" ]] && continue        # fourni par SOPS
  local_value="$(value_of "${key}" "${LOCAL_FILE}")"
  if [[ -z "${local_value}" ]]; then
    case "${key}" in
      FACE_DATA_KEY) local_value="$(rand_b64_32)" ;;
      BACKOFFICE_BOOTSTRAP_TOKEN) local_value="init-$(rand_hex 6)" ;;
      *) local_value="$(rand_hex 24)" ;;
    esac
    printf '%s=%s\n' "${key}" "${local_value}" >> "${LOCAL_FILE}"
    generated=1
  fi
  printf '%s=%s\n' "${key}" "${local_value}" >> "${ENV_FILE}"
done

[[ "${generated}" -eq 1 ]] && echo "Secrets locaux du back-office générés dans ${LOCAL_FILE} (non commité)."
if [[ -z "$(value_of BACKOFFICE_BOOTSTRAP_TOKEN "${ENV_FILE}")" ]]; then
  echo "ERREUR : BACKOFFICE_BOOTSTRAP_TOKEN absent." >&2; exit 1
fi
echo "Jeton d'initialisation du back-office : clé BACKOFFICE_BOOTSTRAP_TOKEN dans .env (ou .env.local)."
