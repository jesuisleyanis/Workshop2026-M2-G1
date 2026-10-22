# syntax=docker/dockerfile:1

# ---- Étape 1 : build Vite ----------------------------------------------------
FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
# VITE_API_BASE est figé AU BUILD (vide = same-origin derrière le WAF).
ARG VITE_API_BASE=""
ENV VITE_API_BASE=${VITE_API_BASE}
# Assets du détecteur de pose (modèle vérifié sha256 + runtime wasm), servis en same-origin.
RUN npm run prepare:vision
RUN npm run build

# ---- Étape 2 : nginx statique, non-root --------------------------------------
FROM nginx:1.27-alpine AS runtime
# Config sans directive "user", pid et temp dirs dans /tmp, écoute sur 8080.
COPY docker/nginx.conf /etc/nginx/nginx.conf
COPY docker/security-headers.conf /etc/nginx/security-headers.conf
RUN rm -f /etc/nginx/conf.d/default.conf
COPY --from=build --chown=nginx:nginx /app/dist /usr/share/nginx/html

USER nginx
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=3s --start-period=5s --retries=3 \
  CMD wget -q -O /dev/null http://127.0.0.1:8080/healthz || exit 1
CMD ["nginx", "-g", "daemon off;"]
