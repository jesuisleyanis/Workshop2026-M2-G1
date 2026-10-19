# syntax=docker/dockerfile:1
# WAF RESILIENCE-ALPHA — Nginx + ModSecurity v3 + OWASP CRS 4 (LTS), seul point exposé.
#
# Base : image officielle OWASP, tag ÉPINGLÉ (version CRS + build daté). Elle fournit
# ModSecurity, le CRS, l'utilisateur non-root `nginx` (uid 101), le certificat auto-signé
# généré au premier démarrage et le rendu des modèles (envsubst) par son entrypoint.
# On ne remplace que le serveur (routage, liste de blocage) et le format des journaux.
FROM owasp/modsecurity-crs:4.25.1-nginx-alpine-202609301109-lts

USER root
# Journal d'audit ModSecurity (JSON) : partagé en lecture seule avec waf-exporter via le
# volume `waf-logs`. Le dossier appartient à nginx pour que le volume nommé hérite des droits.
RUN mkdir -p /var/log/modsec && chown nginx:nginx /var/log/modsec
COPY --chown=root:root templates/conf.d/default.conf.template templates/conf.d/logging.conf.template \
     /etc/nginx/templates/conf.d/
# Liste de blocage par défaut (vide) : le compose monte security/waf/blocked_ips.conf par-dessus.
COPY --chown=root:root blocked_ips.conf /etc/nginx/blocked_ips.conf
USER nginx

ENV PORT=8080 \
    SSL_PORT=8443 \
    MODSEC_RULE_ENGINE=on \
    MODSEC_AUDIT_ENGINE=RelevantOnly \
    MODSEC_AUDIT_LOG=/var/log/modsec/audit.json \
    MODSEC_AUDIT_LOG_FORMAT=JSON \
    MODSEC_AUDIT_LOG_TYPE=Serial \
    # Parties A (IP, URI, code) + H (règles déclenchées) + Z seulement. Les parties par
    # défaut (B, I, J, E...) écrivent en-têtes et CORPS de requête/réponse : jetons
    # Authorization et mots de passe des logins refusés finiraient dans le journal.
    # Reste un risque résiduel : H contient la donnée appariée par la règle (ModSecurity v3
    # ne sait pas la masquer) -> journal sur tmpfs borné, lisible du seul waf-exporter.
    MODSEC_AUDIT_LOG_PARTS=AHZ \
    # Seuls les BLOCAGES sont journalisés (pas les 401/429 d'un flood de logins) : borne la
    # taille du journal et l'exposition de données.
    MODSEC_AUDIT_LOG_RELEVANT_STATUS=^403$ \
    # error_log au niveau crit : à error, nginx y écrit la requête complète (query string,
    # donc jetons éventuels) et ModSecurity la donnée appariée, et Promtail envoie stderr dans
    # Loki. Les erreurs HTTP restent visibles dans l'access log (statut), les blocages via
    # waf-exporter ; les erreurs de configuration (emerg/crit) restent affichées.
    LOGLEVEL=crit \
    BLOCKING_PARANOIA=1

EXPOSE 8080 8443
HEALTHCHECK --interval=15s --timeout=3s --start-period=20s --retries=3 \
  CMD curl -fsk https://127.0.0.1:8443/healthz || exit 1
