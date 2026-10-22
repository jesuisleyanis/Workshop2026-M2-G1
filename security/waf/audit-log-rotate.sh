#!/bin/sh
# Borne le journal d'audit ModSecurity (MODSEC_AUDIT_LOG, JSON Serial, volume `waf-logs`), qui sinon
# grossit sans limite : un scan CRS de quelques milliers de requêtes = dizaines de Mo.
#
# Au-delà de WAF_AUDIT_MAX_BYTES (défaut 50 Mio ; 0 = pas de borne) : copie dans `<log>.1` (UNE génération
# conservée, écrite de façon atomique : temporaire + mv), puis troncature EN PLACE. ModSecurity écrit en
# mode ajout (O_APPEND) sur un descripteur qu'il garde ouvert : renommer le fichier détournerait ses écritures,
# la troncature non. waf-exporter détecte la troncature (taille < position) et repart du début.
# Disque occupé : au plus ~2 x WAF_AUDIT_MAX_BYTES.
#
#   audit-log-rotate.sh          boucle (toutes les WAF_AUDIT_ROTATE_INTERVAL_S, défaut 60 s)
#   audit-log-rotate.sh --once   une seule passe (tests, exploitation)
set -u
LOG="${MODSEC_AUDIT_LOG:-/var/log/modsec/audit.json}"
MAX="${WAF_AUDIT_MAX_BYTES:-52428800}"
INTERVAL="${WAF_AUDIT_ROTATE_INTERVAL_S:-60}"

case "${MAX}" in ''|*[!0-9]*) echo "audit-log-rotate: WAF_AUDIT_MAX_BYTES invalide (${MAX}), 52428800 retenu" >&2; MAX=52428800 ;; esac
case "${INTERVAL}" in ''|0|*[!0-9]*) INTERVAL=60 ;; esac

rotate_once() {
  [ "${MAX}" -gt 0 ] || return 0
  [ -f "${LOG}" ] || return 0
  size=$(wc -c < "${LOG}" | tr -d " ") || return 0
  [ "${size}" -gt "${MAX}" ] || return 0
  cp "${LOG}" "${LOG}.1.tmp" && mv -f "${LOG}.1.tmp" "${LOG}.1" || { rm -f "${LOG}.1.tmp"; return 1; }
  : > "${LOG}"
  echo "audit-log-rotate: ${LOG} (${size} octets > ${MAX}) conservé dans ${LOG}.1 puis tronqué"
}

if [ "${1:-}" = "--once" ]; then
  rotate_once
  exit $?
fi
[ "${MAX}" -gt 0 ] || { echo "audit-log-rotate: WAF_AUDIT_MAX_BYTES=0, journal d'audit non borné"; exit 0; }
while :; do
  rotate_once || echo "audit-log-rotate: rotation impossible (réessai dans ${INTERVAL} s)" >&2
  sleep "${INTERVAL}"
done
