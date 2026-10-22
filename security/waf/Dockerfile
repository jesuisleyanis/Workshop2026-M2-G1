# syntax=docker/dockerfile:1
# WAF RESILIENCE-ALPHA — Nginx + ModSecurity v3 + OWASP Core Rule Set (image officielle CRS).
#   docker build -t resilience/waf security/waf
#
# Base épinglée (R5 reproductibilité) : nginx *unprivileged* (utilisateur `nginx`, uid 101),
# ModSecurity + CRS préinstallés et configurés par les scripts d'entrypoint de l'image
# (variables MODSEC_* / BLOCKING_PARANOIA / ANOMALY_*). L'image tourne non-root : elle ne peut
# écouter que sur des ports > 1024 (8080 / 8443) ; Compose publie 80->8080 et 443->8443.
# Tag + DIGEST : le tag seul a été republié en amont (nouveaux scripts d'entrypoint -> WAF en boucle).
# Mise à jour volontaire : docker buildx imagetools inspect owasp/modsecurity-crs:<tag> puis tests WAF.
FROM owasp/modsecurity-crs:4.25.2-nginx-alpine-lts@sha256:57fd215e2894638a02d235f88510fa2a129d64740f0edb6798ca0e4aa2f02457

USER root

# La configuration Nginx est maîtrisée par le projet (nginx.conf ci-contre) : on retire les
# templates nginx.conf / conf.d de l'image pour que l'entrypoint ne les régénère pas.
# Les templates modsecurity.d sont CONSERVÉS : ils produisent /etc/modsecurity.d/setup.conf
# (ModSecurity + CRS), inclus par notre nginx.conf.
# Les scripts d'entrypoint 93 (PROXY_SSL) et 96 (HTTP3) ne font qu'un `sed` sur conf.d/default.conf,
# supprimé ici : sous `set -e`, ils font échouer le démarrage (WAF en boucle de redémarrage, vu sur
# une republication du tag de base). Ces options ne sont pas utilisées : notre nginx.conf fait foi.
RUN set -eux; \
    rm -f /etc/nginx/templates/nginx.conf.template; \
    rm -rf /etc/nginx/templates/conf.d /etc/nginx/conf.d/*.conf; \
    rm -f /docker-entrypoint.d/93-update-proxy-ssl-config.sh /docker-entrypoint.d/96-update-http3-config.sh

# Certificat TLS AUTO-SIGNÉ généré au build (labo fermé, jamais commité). Déposé là où le script
# `generate-certificate` de l'image le cherche : il détecte la clé et ne régénère rien au démarrage.
RUN set -eux; \
    mkdir -p /etc/nginx/conf; \
    openssl req -x509 -nodes -newkey ec -pkeyopt ec_paramgen_curve:prime256v1 -sha256 -days 365 \
        -keyout /etc/nginx/conf/server.key -out /etc/nginx/conf/server.crt \
        -subj "/CN=resilience-g1/O=RESILIENCE-ALPHA (lab)" \
        -addext "subjectAltName=DNS:localhost,DNS:waf,IP:127.0.0.1,IP:192.168.137.1"; \
    chown -R nginx:nginx /etc/nginx/conf; \
    chmod 600 /etc/nginx/conf/server.key /etc/nginx/conf/server.crt

COPY --chown=nginx:nginx nginx.conf /etc/nginx/nginx.conf
# Deny-list IP : répertoire partagé avec le moteur de remédiation (volume Compose `waf-deny`).
# setgid + group-writable : le moteur (uid 10001, groupe 101) y remplace le fichier (lineinfile),
# nginx (uid 101) le relit au SIGHUP. Le script d'entrypoint recrée le fichier s'il manque.
COPY --chown=nginx:nginx deny/blocked_ips.conf /etc/nginx/deny/blocked_ips.conf
COPY --chmod=0755 docker-entrypoint.d/05-ensure-deny-list.sh /docker-entrypoint.d/05-ensure-deny-list.sh
# Mode « IP réelle » : confiance X-Forwarded-For générée au démarrage (vide par défaut = aucune confiance).
COPY --chmod=0755 docker-entrypoint.d/06-trust-forwarded.sh /docker-entrypoint.d/06-trust-forwarded.sh
RUN echo '# aucune source de confiance (défaut)' > /etc/nginx/conf/realip.conf \
 && chown nginx:nginx /etc/nginx/conf/realip.conf
RUN chown -R nginx:nginx /etc/nginx/deny && chmod 2775 /etc/nginx/deny && chmod 0644 /etc/nginx/deny/blocked_ips.conf

# Journal d'audit ModSecurity (JSON Serial, blocages) : répertoire partagé avec waf-exporter via le volume
# Compose `waf-logs` (MODSEC_AUDIT_LOG=/var/log/modsec/audit.json). Le volume hérite de nginx:nginx 0755
# à sa création ; le fichier (créé par ModSecurity, 0644) est lisible par l'exporteur (groupe 101 en secours).
RUN mkdir -p /var/log/modsec && chown nginx:nginx /var/log/modsec && chmod 0755 /var/log/modsec

# Ports non privilégiés (entrypoint `check-low-port`) et chemins TLS utilisés par nginx.conf.
# ALLOWED_METHODS : défaut CRS « GET HEAD POST OPTIONS » + DELETE (suppression d'un bénéficiaire,
# #43) + PATCH (réglages d'une carte, #47) ; sans eux, la règle 911100 les bloque en 403. PUT reste
# refusé, et nginx.conf ($method_denied) restreint DELETE/PATCH à leur seule route.
# Le Compose surcharge cette valeur (+ PUT) pour l'API d'administration du listener hôte 9443 ;
# le serveur public continue de refuser PUT (405 via $method_denied).
ENV PORT=8080 \
    SSL_PORT=8443 \
    SSL_CERT_FILE=/etc/nginx/conf/server.crt \
    SSL_CERT_KEY_FILE=/etc/nginx/conf/server.key \
    BLOCKING_PARANOIA=1 \
    ALLOWED_METHODS="GET HEAD POST OPTIONS DELETE PATCH" \
    ANOMALY_INBOUND=5 \
    ANOMALY_OUTBOUND=4

USER nginx
EXPOSE 8080 8443

# Le HEALTHCHECK de l'image (curl -sk https://localhost:${SSL_PORT}/healthz) est conservé :
# nginx.conf expose /healthz sans passer par les upstreams.
