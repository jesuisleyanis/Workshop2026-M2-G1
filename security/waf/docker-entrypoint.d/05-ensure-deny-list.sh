#!/bin/sh
# Garantit la présence de la deny-list avant le démarrage de Nginx (la directive `geo ... include`
# exige le fichier). Cas couvert : volume `waf-deny` initialisé vide par le conteneur remediation.
set -eu
DENY_FILE="${WAF_DENY_FILE:-/etc/nginx/deny/blocked_ips.conf}"
if [ ! -f "${DENY_FILE}" ]; then
  mkdir -p "$(dirname "${DENY_FILE}")"
  printf '# deny-list IP du WAF — gérée par la remédiation (waf_deny_ip.yml) ; format geo "<ip> 1;"\n' > "${DENY_FILE}"
  echo "05-ensure-deny-list: ${DENY_FILE} créé (vide)"
fi
exit 0
