#!/bin/sh
# Lance en tâche de fond la borne du journal d'audit ModSecurity (audit-log-rotate.sh, WAF_AUDIT_MAX_BYTES).
# Le processus survit à l'entrypoint (rattaché au PID 1 = nginx) et s'arrête avec le conteneur.
/usr/local/bin/audit-log-rotate.sh &
exit 0
