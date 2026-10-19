#!/bin/sh
# Génère la conf nginx depuis le template (envsubst) dans /tmp (compatible read_only + tmpfs), puis lance nginx.
set -eu
: "${REMEDIATION_UPSTREAM:=remediation:8005}"
: "${REMEDIATION_AUTH_HEADER:=}"
: "${DNS_RESOLVER:=127.0.0.11}"
: "${ASSISTANT_UPSTREAM:=assistant:8006}"
export REMEDIATION_UPSTREAM REMEDIATION_AUTH_HEADER DNS_RESOLVER ASSISTANT_UPSTREAM

mkdir -p /tmp/nginx-conf
envsubst '${REMEDIATION_UPSTREAM} ${REMEDIATION_AUTH_HEADER} ${DNS_RESOLVER} ${ASSISTANT_UPSTREAM}' \
  < /etc/nginx/templates/dashboard.conf.template > /tmp/nginx-conf/dashboard.conf

exec nginx -g 'daemon off;'
