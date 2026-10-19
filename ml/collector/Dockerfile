# syntax=docker/dockerfile:1
# Build depuis la RACINE du dépôt :
#   docker build -f ml/collector/Dockerfile -t resilience/collector .
FROM python:3.12-slim AS builder
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
COPY libs/python/resilience_common /tmp/resilience_common
COPY ml/collector/requirements.txt /tmp/requirements.txt
RUN pip install -r /tmp/requirements.txt "/tmp/resilience_common[fastapi]"

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    PROMETHEUS_URL=http://prometheus:9090
RUN groupadd --system --gid 10004 collector \
 && useradd --system --uid 10004 --gid collector --no-create-home --shell /usr/sbin/nologin collector
COPY --from=builder /opt/venv /opt/venv
WORKDIR /app
COPY --chown=root:root ml/__init__.py ml/__init__.py
COPY --chown=root:root ml/shared ml/shared
COPY --chown=root:root ml/collector ml/collector
USER 10004:10004
EXPOSE 8004
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
  CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8004/health', timeout=2).status == 200 else 1)"]
CMD ["uvicorn", "ml.collector.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8004"]
