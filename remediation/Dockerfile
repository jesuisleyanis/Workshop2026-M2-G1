# Moteur de remédiation — image durcie.
# Contexte de build = RACINE du dépôt (la lib partagée y est copiée) :
#   docker build -f remediation/Dockerfile -t resilience/remediation .
#
# Durcissement : multi-stage, python:slim, utilisateur non-root (uid 10001), aucun outil de
# build dans l'image finale, HEALTHCHECK sans curl. AUCUN accès au socket Docker : l'image ne
# déclare pas de volume docker.sock et le moteur parle uniquement HTTP au docker-socket-proxy.

FROM python:3.12-slim AS builder
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN python -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH
COPY remediation/requirements.txt /tmp/requirements.txt
COPY libs/python/resilience_common /tmp/resilience_common
RUN pip install -r /tmp/requirements.txt /tmp/resilience_common

FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH=/opt/venv/bin:$PATH \
    INCIDENTS_DB=/var/lib/remediation/incidents.db \
    DECISION_TABLE=/app/decision_table.yml \
    VERIFY_TX_PATH=/opt/scripts/verify_tx \
    ANSIBLE_PRIVATE_DATA_DIR=/opt/ansible \
    DOCKER_PROXY_URL=http://docker-socket-proxy:2375
RUN groupadd --system --gid 10001 remediation \
 && useradd --system --uid 10001 --gid 10001 --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin remediation \
 && mkdir -p /var/lib/remediation/export \
 && chown -R 10001:10001 /var/lib/remediation
COPY --from=builder /opt/venv /opt/venv
WORKDIR /app
# Code et table en lecture seule pour l'utilisateur d'exécution (propriété root).
COPY remediation/*.py remediation/decision_table.yml /app/
COPY remediation/actions /app/actions
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
