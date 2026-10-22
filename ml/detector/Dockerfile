# syntax=docker/dockerfile:1
# Build depuis la RACINE du dépôt (le contexte doit contenir libs/ et ml/) :
#   docker build -f ml/detector/Dockerfile -t resilience/detector .
# Le modèle est ENTRAÎNÉ AU BUILD (étape `trainer`) : les artefacts ne sont pas
# versionnés (.gitignore) et le scikit-learn d'entraînement est ainsi celui du runtime.
# Données : ml/training/data/baseline_real.csv si présent (vraies séries Prometheus,
# cf. ml/training/README.md), sinon baseline synthétique ; seuil calibré par
# ml/training/data/calibration.json si présent.
FROM python:3.12-slim AS builder
ENV PIP_DISABLE_PIP_VERSION_CHECK=1
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
COPY libs/python/resilience_common /tmp/resilience_common
COPY ml/detector/requirements.txt /tmp/requirements.txt
RUN --mount=type=cache,target=/root/.cache/pip pip install -r /tmp/requirements.txt "/tmp/resilience_common[fastapi]"

# Outils ML de DEV (make ml-tools / train / calibrate / test-ml) : même Python et même
# scikit-learn que le runtime, sans rien installer sur le poste. Le dépôt est monté en
# /src au lancement ; cette étape n'entre pas dans l'image finale du detector.
FROM builder AS ml-tools
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN --mount=type=cache,target=/root/.cache/pip pip install "/tmp/resilience_common[fastapi,test]"
WORKDIR /src

FROM builder AS trainer
ARG MODEL_VERSION=1.2.0
WORKDIR /build
COPY ml/__init__.py ml/__init__.py
COPY ml/shared ml/shared
COPY ml/training ml/training
RUN set -eu; \
    args="--version ${MODEL_VERSION} --out /build/artifacts"; \
    if [ -f ml/training/data/baseline_real.csv ]; then args="$args --data ml/training/data/baseline_real.csv"; fi; \
    if [ -f ml/training/data/calibration.json ]; then args="$args --calibration ml/training/data/calibration.json"; fi; \
    python -m ml.training.train $args

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
COPY --from=trainer --chown=root:root /build/artifacts/model.joblib /build/artifacts/baseline_stats.json /app/artifacts/
USER 10003:10003
EXPOSE 8003
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
  CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8003/health', timeout=2).status == 200 else 1)"]
# Écoute sur toutes les interfaces DU CONTENEUR ; l'exposition réelle est décidée par le
# compose (réseau `app` interne, aucun `ports:`).
CMD ["uvicorn", "ml.detector.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8003"]
