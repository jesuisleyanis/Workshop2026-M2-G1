"""Service FastAPI du detector (port interne 8003, réseau `app`).

Routes : GET /health, /ready, /metrics, GET /api/v1/status.
Boucle de fond : attend chaque nouvelle collecte du collector (attente longue, `?after=<seq>`)
— repli : relève toutes les POLL_INTERVAL_SECONDS si le collector ne répond pas —
calcule le score ML, expose `resilience_anomaly_score{service}` et, au-dessus du seuil,
POST un AnomalyEvent vers la remédiation.

Configuration (variables d'environnement) :
  MODEL_DIR               dossier model.joblib + baseline_stats.json   (/app/artifacts)
  COLLECTOR_URL           http://collector:8004
  REMEDIATION_URL         http://remediation:8005/events
  REMEDIATION_TOKEN       token Bearer (ou REMEDIATION_TOKEN_FILE : secret monté, SOPS)
  TARGET_SERVICE          valeur du label `service` / de l'événement        (payment-api)
  POLL_INTERVAL_SECONDS   1    pause après une relève en échec (ou entre relèves si attente longue coupée)
  FEATURES_WAIT_SECONDS   5    attente longue max côté collector (0 = relève périodique classique)
  EVENT_COOLDOWN_SECONDS  60
  ANOMALY_THRESHOLD       surcharge optionnelle du seuil de baseline_stats.json
  ANOMALY_CONFIRM_WINDOWS surcharge optionnelle du nombre de fenêtres de confirmation (calibration)
  LOKI_URL                http://loki:3100 — IP source dominante des logs WAF ("" = désactivé)
  SOURCE_IP_WINDOW_SECONDS 30   fenêtre de recherche de l'IP source
  SOURCE_IP_MIN_SHARE     0.6  part minimale des lignes WAF pour retenir une IP
  SOURCE_IP_EXCLUDE       réseaux jamais candidats (CIDR, virgules) : réseaux Docker internes
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
from ml.detector.source_ip import LokiSourceResolver
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
                 http: httpx.AsyncClient | None = None, load_error: str | None = None,
                 wait: float = 0.0) -> None:
        self.detector = detector
        self.collector_url = collector_url.rstrip("/")
        self.interval = interval
        self.wait = wait  # attente longue côté collector (s) ; 0 = relève périodique
        self.http = http or httpx.AsyncClient(timeout=5.0 + wait)
        self.load_error = load_error
        self.collector_ok = False
        self.last_poll_ok_at: float | None = None
        self.last_seq: int | None = None  # dernière collecte scorée (jamais deux fois la même)

    async def poll_once(self) -> bool:
        """Une relève du collector + traitement ; True si elle a abouti. Ne lève jamais."""
        loop = asyncio.get_running_loop()
        params = {}
        if self.wait and self.last_seq is not None:
            params = {"after": self.last_seq, "wait": self.wait}
        try:
            resp = await self.http.get(f"{self.collector_url}/api/v1/features", params=params)
            if resp.status_code != 200:
                raise httpx.HTTPError(f"collector HTTP {resp.status_code}")
            body = resp.json()
            if body.get("feature_names") != list(FEATURE_NAMES):
                raise ValueError("feature_names du collector incompatibles avec ml.shared.features")
            vector = [float(v) for v in body["vector"]]
            seq = body.get("seq")
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            if self.collector_ok or self.last_poll_ok_at is None:
                log.warning(f"Pas de features exploitables: {exc}")
            self.collector_ok = False
            return False
        self.collector_ok = True
        self.last_poll_ok_at = loop.time()
        if seq is not None and seq == self.last_seq:
            return True  # attente longue expirée sans nouvelle collecte : rien de neuf à scorer
        self.last_seq = seq
        if self.detector is not None:
            await self.detector.process(vector)
        return True


def create_app(runtime: Runtime | None = None, start_loop: bool = True) -> FastAPI:
    if runtime is None:
        interval = float(os.getenv("POLL_INTERVAL_SECONDS", "1"))
        wait = float(os.getenv("FEATURES_WAIT_SECONDS", "5"))
        rem = RemediationClient(
            os.getenv("REMEDIATION_URL", "http://remediation:8005/events"), read_token()
        )
        loki_url = os.getenv("LOKI_URL", "http://loki:3100")
        resolver = LokiSourceResolver(
            loki_url,
            window_s=int(os.getenv("SOURCE_IP_WINDOW_SECONDS", "30")),
            min_share=float(os.getenv("SOURCE_IP_MIN_SHARE", "0.6")),
            exclude=os.getenv("SOURCE_IP_EXCLUDE", ""),
        ) if loki_url else None
        try:
            model = load_model(os.getenv("MODEL_DIR", "/app/artifacts"))
            threshold = os.getenv("ANOMALY_THRESHOLD")
            confirm = os.getenv("ANOMALY_CONFIRM_WINDOWS")  # surcharge de la calibration
            detector = Detector(
                model, rem,
                service=os.getenv("TARGET_SERVICE", "payment-api"),
                threshold=float(threshold) if threshold else None,
                cooldown=float(os.getenv("EVENT_COOLDOWN_SECONDS", "60")),
                source_resolver=resolver,
                confirm_windows=int(confirm) if confirm else None,
            )
            err = None
            log.info(f"Modèle v{model.version} chargé, seuil={detector.threshold}")
        except ModelLoadError as exc:
            detector, err = None, str(exc)
            log.error(f"Modèle non chargé: {exc}")
        runtime = Runtime(detector, os.getenv("COLLECTOR_URL", "http://collector:8004"),
                          interval, load_error=err, wait=wait)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        stop = asyncio.Event()

        async def loop() -> None:
            while not stop.is_set():
                ok = await runtime.poll_once()
                if ok and runtime.wait and runtime.last_seq is not None:
                    continue  # attente longue : c'est le collector qui cadence, pas de pause
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
                if runtime.detector.source_resolver:
                    await runtime.detector.source_resolver.aclose()

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
