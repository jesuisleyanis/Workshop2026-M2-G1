# syntax=docker/dockerfile:1
# Contexte de build = RACINE du dépôt (le service installe les libs partagées de libs/python/) :
#   docker build -f services/auth/Dockerfile -t resilience/auth .

# ---- Étape 1 : build des dépendances dans un venv isolé --------------------------------
FROM python:3.12-slim AS builder
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
WORKDIR /build
COPY services/auth/requirements.txt ./requirements.txt
RUN pip install -r requirements.txt
COPY libs/python/resilience_common ./libs/resilience_common
COPY libs/python/resilience_db ./libs/resilience_db
COPY services/auth/pyproject.toml ./service/pyproject.toml
COPY services/auth/src ./service/src
RUN pip install --no-deps ./libs/resilience_common ./libs/resilience_db ./service

# ---- Étape 2 : image d'exécution minimale ---------------------------------------------
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"
# Utilisateur système non-root, sans shell ni home.
RUN groupadd --system --gid 10001 app \
 && useradd --system --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app
COPY --from=builder /opt/venv /opt/venv
WORKDIR /app
USER 10001:10001
EXPOSE 8002

# Aucun secret dans l'image : JWT_SECRET, POSTGRES_PASSWORD, INTERNAL_TOKEN
# sont injectés à l'exécution (SOPS -> variables d'env ou *_FILE).
# Compatible read_only: true (aucune écriture disque ; pas de .pyc).
HEALTHCHECK --interval=10s --timeout=3s --start-period=15s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8002/health', timeout=2)"]

# 1 worker : l'état du rate-limit est en mémoire (cf. README). Logs applicatifs JSON sur stdout ;
# les access-logs texte d'uvicorn sont désactivés pour garder stdout 100 % JSON (Promtail).
CMD ["uvicorn", "auth_service.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8002", "--no-access-log", "--log-level", "warning"]
