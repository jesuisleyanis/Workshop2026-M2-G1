# syntax=docker/dockerfile:1
# Assistant opérateur RAG - lecture documentaire seule.
# CONTEXTE DE BUILD = RACINE DU REPO (la lib commune est hors de assistant/) :
#   docker build -f assistant/Dockerfile -t resilience/assistant .
FROM python:3.12-slim AS builder
ENV PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /build
COPY assistant/requirements.txt ./requirements.txt
COPY libs/python/resilience_common ./resilience_common
RUN --mount=type=cache,target=/root/.cache/pip python -m venv /opt/venv \
 && /opt/venv/bin/pip install -r requirements.txt ./resilience_common

FROM python:3.12-slim
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    ANONYMIZED_TELEMETRY=False \
    CHROMA_PATH=/data/chroma DOCS_DIR=/data/docs \
    DECISION_TABLE_PATH=/data/remediation/decision_table.yml \
    INCIDENTS_PATH=/data/incidents/incidents.json
# Utilisateur non-root sans shell ni home inscriptible ; /data/chroma = volume persistant.
RUN useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin assistant \
 && mkdir -p /data/chroma && chown -R assistant:assistant /data
COPY --from=builder /opt/venv /opt/venv
WORKDIR /srv
COPY --chown=root:root assistant/app ./app
USER 10001
EXPOSE 8006
# Logs applicatifs = JSON du contrat (middleware) ; logs uvicorn texte réduits aux warnings.
# Pas de curl dans l'image : la sonde utilise la stdlib. /health = liveness (ne dépend pas d'Ollama).
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8006/health', timeout=3).status == 200 else 1)"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8006", "--no-server-header", "--no-access-log", "--log-level", "warning"]
