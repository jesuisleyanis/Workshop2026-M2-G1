#!/usr/bin/env bash
# Complète le .env déchiffré avec les secrets du back-office facial absents de SOPS.
#
# FACE_INTERNAL_TOKEN, FACE_DATA_KEY et BACKOFFICE_BOOTSTRAP_TOKEN sont propres au PC Hôte :
# s'ils ne sont pas (encore) dans security/sops/secrets.enc.env, ils sont générés UNE fois
# dans .env.local (0600, non commité) puis recopiés dans .env à chaque `make decrypt`.
# FACE_DATA_KEY doit rester stable : la perdre rend les enrôlements illisibles (réenrôlement).
# Une valeur présente dans SOPS l'emporte toujours sur .env.local (avertissement sur stderr si
# les deux diffèrent : seul le NOM de la clé est affiché, jamais sa valeur).
#
# Surcharges NON secrètes propres au poste (jamais générées, seulement recopiées si présentes
# dans .env.local) : MQTT_BIND_ADDR (ex. 127.0.0.1 sur une machine sans l'IP du hotspot).
# Elles remplacent la valeur de SOPS : c'est leur raison d'être, et elles survivent à `make decrypt`.
set -euo pipefail

ROOT="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
ENV_FILE="${ROOT}/.env"
LOCAL_FILE="${ROOT}/.env.local"
SECRET_KEYS=(FACE_INTERNAL_TOKEN FACE_DATA_KEY BACKOFFICE_BOOTSTRAP_TOKEN)
LOCAL_OVERRIDES=(MQTT_BIND_ADDR)

rand_b64_32() {
  if command -v openssl >/dev/null 2>&1; then openssl rand -base64 32
  else python3 -c 'import base64,os;print(base64.b64encode(os.urandom(32)).decode())'; fi
}
rand_hex() {
  if command -v openssl >/dev/null 2>&1; then openssl rand -hex "$1"
  else python3 -c "import secrets;print(secrets.token_hex($1))"; fi
}
value_of() {  # value_of KEY FILE -> valeur (vide si absente ; \r d'un fichier CRLF retiré)
  [[ -f "$2" ]] || return 0
  sed -n "s/^$1=//p" "$2" | tail -n 1 | tr -d '\r' | sed -e "s/^['\"]//" -e "s/['\"]$//"
}
ensure_trailing_newline() {  # sans \n final, la ligne ajoutée serait collée à la dernière valeur
  if [[ -s "$1" && -n "$(tail -c 1 "$1")" ]]; then printf '\n' >> "$1"; fi
}

# .env absent (script lancé seul) : créé d'emblée en 0600, comme .env.local.
[[ -f "${ENV_FILE}" ]] || (umask 077; : > "${ENV_FILE}")
(umask 077; touch "${LOCAL_FILE}")
chmod 600 "${LOCAL_FILE}"
ensure_trailing_newline "${ENV_FILE}"
ensure_trailing_newline "${LOCAL_FILE}"

generated=0
for key in "${SECRET_KEYS[@]}"; do
  env_value="$(value_of "${key}" "${ENV_FILE}")"
  local_value="$(value_of "${key}" "${LOCAL_FILE}")"
  if [[ -n "${env_value}" ]]; then                                  # fourni par SOPS
    if [[ -n "${local_value}" && "${local_value}" != "${env_value}" ]]; then
      echo "ATTENTION : ${key} diffère entre SOPS (.env) et .env.local ; la valeur de SOPS est utilisée." >&2
      if [[ "${key}" == FACE_DATA_KEY ]]; then
        echo "  Les enrôlements chiffrés avec l'autre clé deviendront illisibles (réenrôlement) : alignez les deux fichiers." >&2
      fi
    fi
    continue
  fi
  if [[ -z "${local_value}" ]]; then
    case "${key}" in
      FACE_DATA_KEY) local_value="$(rand_b64_32)" ;;
      BACKOFFICE_BOOTSTRAP_TOKEN) local_value="init-$(rand_hex 6)" ;;
      *) local_value="$(rand_hex 24)" ;;
    esac
    printf '%s=%s\n' "${key}" "${local_value}" >> "${LOCAL_FILE}"
    generated=1
  fi
  sed -i "/^${key}=/d" "${ENV_FILE}"                                # ligne vide éventuelle (KEY=)
  printf '%s=%s\n' "${key}" "${local_value}" >> "${ENV_FILE}"
done

for key in "${LOCAL_OVERRIDES[@]}"; do
  local_value="$(value_of "${key}" "${LOCAL_FILE}")"
  [[ -n "${local_value}" ]] || continue                             # jamais générée
  if [[ "$(value_of "${key}" "${ENV_FILE}")" != "${local_value}" ]]; then
    sed -i "/^${key}=/d" "${ENV_FILE}"
    printf '%s=%s\n' "${key}" "${local_value}" >> "${ENV_FILE}"
    echo "Surcharge locale appliquée depuis .env.local : ${key}=${local_value}"
  fi
done

[[ "${generated}" -eq 1 ]] && echo "Secrets locaux du back-office générés dans ${LOCAL_FILE} (non commité)."
if [[ -z "$(value_of BACKOFFICE_BOOTSTRAP_TOKEN "${ENV_FILE}")" ]]; then
  echo "ERREUR : BACKOFFICE_BOOTSTRAP_TOKEN absent." >&2; exit 1
fi
echo "Jeton d'initialisation du back-office : clé BACKOFFICE_BOOTSTRAP_TOKEN dans .env (ou .env.local)."
