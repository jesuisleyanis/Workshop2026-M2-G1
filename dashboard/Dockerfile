# syntax=docker/dockerfile:1

# ---- Étape 1 : build Vite ----------------------------------------------------
FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
# Figés AU BUILD. Défaut : flux proxifié par nginx sur /remediation/stream.
ARG VITE_REMEDIATION_BASE="/remediation"
ARG VITE_GRAFANA_BASE="http://localhost:3000"
ENV VITE_REMEDIATION_BASE=${VITE_REMEDIATION_BASE} \
    VITE_GRAFANA_BASE=${VITE_GRAFANA_BASE}
RUN npm run build

# ---- Étape 2 : nginx statique + proxy SSE, non-root --------------------------
FROM nginx:1.27-alpine AS runtime
COPY docker/nginx.conf /etc/nginx/nginx.conf
COPY docker/security-headers.conf /etc/nginx/security-headers.conf
COPY docker/dashboard.conf.template /etc/nginx/templates/dashboard.conf.template
COPY --chmod=755 docker/entrypoint.sh /entrypoint.sh
# Garde-fou CRLF (checkout Windows sans .gitattributes) : un shebang `#!/bin/sh\r` est introuvable.
RUN sed -i 's/\r$//' /entrypoint.sh \
 && rm -f /etc/nginx/conf.d/default.conf
COPY --from=build --chown=nginx:nginx /app/dist /usr/share/nginx/html

ENV REMEDIATION_UPSTREAM=remediation:8005 \
    REMEDIATION_AUTH_HEADER="" \
    DNS_RESOLVER=127.0.0.11

USER nginx
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=3s --start-period=5s --retries=3 \
  CMD wget -q -O /dev/null http://127.0.0.1:8080/healthz || exit 1
ENTRYPOINT ["/entrypoint.sh"]
