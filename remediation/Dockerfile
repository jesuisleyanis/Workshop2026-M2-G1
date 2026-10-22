# syntax=docker/dockerfile:1
# Moteur de remédiation — image durcie.
# Contexte de build = RACINE du dépôt (la lib partagée y est copiée) :
#   docker build -f remediation/Dockerfile -t resilience/remediation .
#
# Durcissement : multi-stage, python:slim, utilisateur non-root (uid 10001), aucun outil de
# build dans l'image finale, HEALTHCHECK sans curl. AUCUN accès au socket Docker : l'image ne
# déclare pas de volume docker.sock et le moteur parle uniquement HTTP au docker-socket-proxy.
#
# Plan d'exécution embarqué (tout s'exécute DANS ce conteneur, jamais via `docker exec`) :
#   - /opt/scripts/verify_tx          transaction de contrôle (VERIFY_TX_PATH), rejouée via le WAF ;
#   - /opt/ansible/project/*.yml      playbooks de remédiation (hosts: localhost) pour ansible-runner ;
#   - pg_restore / psql (client 16)   restauration des dumps (réseau `data`, PG_BACKUP_DIR en lecture seule).

FROM python:3.12-slim AS builder
ENV PIP_DISABLE_PIP_VERSION_CHECK=1
RUN python -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH
COPY remediation/requirements.txt /tmp/requirements.txt
COPY libs/python/resilience_common /tmp/resilience_common
RUN --mount=type=cache,target=/root/.cache/pip pip install -r /tmp/requirements.txt /tmp/resilience_common

FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH=/opt/venv/bin:$PATH \
    INCIDENTS_DB=/var/lib/remediation/incidents.db \
    DECISION_TABLE=/app/decision_table.yml \
    VERIFY_TX_PATH=/opt/scripts/verify_tx \
    ANSIBLE_PROJECT_DIR=/opt/ansible/project \
    ANSIBLE_PRIVATE_DATA_DIR=/tmp/ansible-runner \
    ANSIBLE_HOME=/tmp/.ansible \
    ANSIBLE_LOCAL_TEMP=/tmp/.ansible/tmp \
    ANSIBLE_REMOTE_TMP=/tmp/.ansible/tmp \
    PG_BACKUP_DIR=/opt/backups \
    WAF_DENY_FILE=/etc/resilience/waf-deny/blocked_ips.conf \
    DOCKER_PROXY_URL=http://docker-socket-proxy:2375
# Client Postgres 16 (même version majeure que le serveur `postgres:16`) depuis le dépôt PGDG,
# pour pg_restore/psql ; les outils de téléchargement sont retirés de l'image finale.
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends ca-certificates curl gnupg; \
    curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc | gpg --dearmor -o /usr/share/keyrings/pgdg.gpg; \
    . /etc/os-release; \
    echo "deb [signed-by=/usr/share/keyrings/pgdg.gpg] https://apt.postgresql.org/pub/repos/apt ${VERSION_CODENAME}-pgdg main" > /etc/apt/sources.list.d/pgdg.list; \
    apt-get update; \
    apt-get install -y --no-install-recommends postgresql-client-16; \
    apt-get purge -y --auto-remove curl gnupg; \
    rm -rf /var/lib/apt/lists/*
RUN groupadd --system --gid 10001 remediation \
 && useradd --system --uid 10001 --gid 10001 --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin remediation \
 && mkdir -p /var/lib/remediation/export /opt/backups /etc/resilience/waf-deny \
 && chown -R 10001:10001 /var/lib/remediation \
 # Point de montage du volume `waf-deny` partagé avec le WAF (gid 101 = groupe nginx du WAF) :
 # si ce conteneur initialise le volume, le WAF (uid 101) doit pouvoir y créer/lire le fichier.
 && chown 10001:101 /etc/resilience/waf-deny && chmod 2775 /etc/resilience/waf-deny
COPY --from=builder /opt/venv /opt/venv
WORKDIR /app
# Code et table en lecture seule pour l'utilisateur d'exécution (propriété root).
COPY remediation/*.py remediation/decision_table.yml /app/
COPY remediation/actions /app/actions
# Plan d'exécution : script de vérification + playbooks de remédiation (lecture seule).
COPY --chmod=0755 scripts/verify_tx /opt/scripts/verify_tx
COPY infra/ansible/playbooks/remediation /opt/ansible/project
# Seul point inscriptible : le journal d'incidents (volume dédié) ; export/ = copie JSON pour
# l'assistant (export_journal.py), volume nommé `incidents-export` en Compose.
VOLUME ["/var/lib/remediation"]
USER 10001:10001
EXPOSE 8005
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
  CMD ["python", "-c", "import sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8005/health', timeout=2).status == 200 else 1)"]
# Écoute sur toutes les interfaces DU CONTENEUR (nécessaire pour les autres services du réseau
# `app`) ; l'exposition réelle est décidée par Compose : aucun `ports:`, jamais le réseau `edge`.
CMD ["uvicorn", "--factory", "main:app_factory", "--host", "0.0.0.0", "--port", "8005", "--no-server-header"]
