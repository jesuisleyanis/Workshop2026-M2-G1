"""Service FastAPI du detector (port interne 8003, réseau `app`).

Routes : GET /health, /ready, /metrics, GET /api/v1/status.
Boucle de fond : relève les features du collector toutes les POLL_INTERVAL_SECONDS,
calcule le score ML, expose `resilience_anomaly_score{service}` et, au-dessus du seuil,
POST un AnomalyEvent vers la remédiation.

Configuration (variables d'environnement) :
  MODEL_DIR               dossier model.joblib + baseline_stats.json   (/app/artifacts)
  COLLECTOR_URL           http://collector:8004
  REMEDIATION_URL         http://remediation:8005/events
  REMEDIATION_TOKEN       token Bearer (ou REMEDIATION_TOKEN_FILE : secret monté, SOPS)
  TARGET_SERVICE          valeur du label `service` / de l'événement        (payment-api)
  POLL_INTERVAL_SECONDS   15
  EVENT_COOLDOWN_SECONDS  60
  ANOMALY_THRESHOLD       surcharge optionnelle du seuil de baseline_stats.json
"""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from resilience_common import get_logger
from resilience_common.metrics import instrument

from ml.detector.core import Detector, RemediationClient
from ml.detector.model import ModelLoadError, load_model
from ml.shared.features import FEATURE_NAMES

SERVICE = "detector"
log = get_logger(SERVICE)


def read_token() -> str | None:
    """Token de la remédiation : fichier de secret monté en priorité, sinon variable d'env."""
    token_file = os.getenv("REMEDIATION_TOKEN_FILE")
    if token_file and Path(token_file).is_file():
        return Path(token_file).read_text().strip() or None
    return os.getenv("REMEDIATION_TOKEN") or None


class Runtime:
    """État partagé de la boucle (observable par /ready et /status)."""

    def __init__(self, detector: Detector | None, collector_url: str, interval: float,
                 http: httpx.AsyncClient | None = None, load_error: str | None = None) -> None:
        self.detector = detector
        self.collector_url = collector_url.rstrip("/")
        self.interval = interval
        self.http = http or httpx.AsyncClient(timeout=5.0)
        self.load_error = load_error
        self.collector_ok = False
        self.last_poll_ok_at: float | None = None

    async def poll_once(self) -> None:
        """Une relève du collector + traitement. Ne lève jamais (la boucle doit survivre)."""
        loop = asyncio.get_running_loop()
        try:
            resp = await self.http.get(f"{self.collector_url}/api/v1/features")
            if resp.status_code != 200:
                raise httpx.HTTPError(f"collector HTTP {resp.status_code}")
            body = resp.json()
            if body.get("feature_names") != list(FEATURE_NAMES):
                raise ValueError("feature_names du collector incompatibles avec ml.shared.features")
            vector = [float(v) for v in body["vector"]]
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            if self.collector_ok or self.last_poll_ok_at is None:
                log.warning(f"Pas de features exploitables: {exc}")
            self.collector_ok = False
            return
        self.collector_ok = True
        self.last_poll_ok_at = loop.time()
        if self.detector is not None:
            await self.detector.process(vector)


def create_app(runtime: Runtime | None = None, start_loop: bool = True) -> FastAPI:
    if runtime is None:
        interval = float(os.getenv("POLL_INTERVAL_SECONDS", "15"))
        rem = RemediationClient(
            os.getenv("REMEDIATION_URL", "http://remediation:8005/events"), read_token()
        )
        try:
            model = load_model(os.getenv("MODEL_DIR", "/app/artifacts"))
            threshold = os.getenv("ANOMALY_THRESHOLD")
            detector = Detector(
                model, rem,
                service=os.getenv("TARGET_SERVICE", "payment-api"),
                threshold=float(threshold) if threshold else None,
                cooldown=float(os.getenv("EVENT_COOLDOWN_SECONDS", "60")),
            )
            err = None
            log.info(f"Modèle v{model.version} chargé, seuil={detector.threshold}")
        except ModelLoadError as exc:
            detector, err = None, str(exc)
            log.error(f"Modèle non chargé: {exc}")
        runtime = Runtime(detector, os.getenv("COLLECTOR_URL", "http://collector:8004"),
                          interval, load_error=err)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        stop = asyncio.Event()

        async def loop() -> None:
            while not stop.is_set():
                await runtime.poll_once()
                try:
                    await asyncio.wait_for(stop.wait(), timeout=runtime.interval)
                except asyncio.TimeoutError:
                    pass

        task = asyncio.create_task(loop()) if start_loop else None
        try:
            yield
        finally:
            stop.set()
            if task:
                await task
            await runtime.http.aclose()
            if runtime.detector:
                await runtime.detector.remediation.aclose()

    app = FastAPI(title="RESILIENCE detector", version="1.0.0", lifespan=lifespan)
    app.state.runtime = runtime
    instrument(app, SERVICE)

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    @app.get("/ready")
    async def ready():
        det = runtime.detector
        problems = []
        if det is None:
            problems.append(f"modèle: {runtime.load_error}")
        else:
            if not det.remediation.configured:
                problems.append("REMEDIATION_TOKEN absent")
            if not runtime.collector_ok:
                problems.append("collector sans données")
        if problems:
            return JSONResponse(status_code=503, content={"status": "not_ready", "problems": problems})
        return {"status": "ready"}

    @app.get("/api/v1/status")
    async def status() -> dict:
        det = runtime.detector
        last = det.last_decision if det else None
        return {
            "model_version": det.model.version if det else None,
            "threshold": det.threshold if det else None,
            "collector_ok": runtime.collector_ok,
            "last_score": last.score if last else None,
            "last_is_anomaly": last.is_anomaly if last else None,
            "last_trigger": last.trigger if last else None,
            "last_event_id": last.event.event_id if last and last.event else None,
        }

    return app
