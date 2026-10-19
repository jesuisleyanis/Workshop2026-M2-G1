# syntax=docker/dockerfile:1
# Build depuis la RACINE du dépôt (le contexte doit contenir libs/ et ml/) :
#   python -m ml.training.train                       # produit ml/training/artifacts/
#   docker build -f ml/detector/Dockerfile -t resilience/detector .
FROM python:3.12-slim AS builder
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
COPY libs/python/resilience_common /tmp/resilience_common
COPY ml/detector/requirements.txt /tmp/requirements.txt
RUN pip install -r /tmp/requirements.txt "/tmp/resilience_common[fastapi]"

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    MODEL_DIR=/app/artifacts
# Utilisateur non-root sans shell ni home inscriptible
RUN groupadd --system --gid 10003 detector \
 && useradd --system --uid 10003 --gid detector --no-create-home --shell /usr/sbin/nologin detector
COPY --from=builder /opt/venv /opt/venv
WORKDIR /app
COPY --chown=root:root ml/__init__.py ml/__init__.py
COPY --chown=root:root ml/shared ml/shared
COPY --chown=root:root ml/detector ml/detector
COPY --chown=root:root ml/training/artifacts/model.joblib ml/training/artifacts/baseline_stats.json /app/artifacts/
USER 10003:10003
EXPOSE 8003
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
  CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8003/health', timeout=2).status == 200 else 1)"]
# Écoute sur toutes les interfaces DU CONTENEUR ; l'exposition réelle est décidée par le
# compose (réseau `app` interne, aucun `ports:`).
CMD ["uvicorn", "ml.detector.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8003"]
