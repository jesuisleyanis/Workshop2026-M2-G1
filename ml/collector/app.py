"""Service FastAPI du collector (port interne 8004, réseau `app`).

Routes : GET /health, /ready, /metrics et GET /api/v1/features (consommé par le detector).
Aucun secret ; n'écoute que sur le réseau interne (publication de port interdite par le compose).
"""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from prometheus_client import Counter, Gauge, REGISTRY

from resilience_common import get_logger
from resilience_common.metrics import instrument

from ml.collector.collector import Collector, PrometheusClient, build_queries

SERVICE = "collector"
log = get_logger(SERVICE)


def _metric(cls, name: str, doc: str, **kw):
    """Crée la métrique ou la réutilise (évite les doublons si l'app est recréée en test)."""
    existing = REGISTRY._names_to_collectors.get(name)  # noqa: SLF001
    return existing if existing is not None else cls(name, doc, **kw)


collections_total = _metric(
    Counter, "resilience_collector_collections_total", "Collectes de features.",
    labelnames=("result",),
)
feature_missing = _metric(
    Gauge, "resilience_collector_missing_features",
    "Nombre de features sans donnée lors de la dernière collecte.",
)


def create_app(collector: Collector | None = None, start_loop: bool = True) -> FastAPI:
    interval = float(os.getenv("COLLECT_INTERVAL_SECONDS", "15"))
    if collector is None:
        prom = PrometheusClient(os.getenv("PROMETHEUS_URL", "http://prometheus:9090"))
        collector = Collector(
            prom,
            queries=build_queries(os.getenv("PROM_RATE_WINDOW", "30s")),
            interval=interval,
        )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        stop = asyncio.Event()
        task = asyncio.create_task(_loop(collector, stop)) if start_loop else None
        try:
            yield
        finally:
            stop.set()
            if task:
                await task
            await collector.prom.aclose()

    app = FastAPI(title="RESILIENCE collector", version="1.0.0", lifespan=lifespan)
    app.state.collector = collector
    instrument(app, SERVICE)

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    @app.get("/ready")
    async def ready():
        # Prêt = Prometheus joignable ET une collecte récente a produit un vecteur.
        snap = collector.fresh()
        if snap is None:
            return JSONResponse(
                status_code=503,
                content={"status": "not_ready", "reason": collector.last_error or "pas encore de collecte"},
            )
        return {"status": "ready"}

    @app.get("/api/v1/features")
    async def features():
        snap = collector.fresh()
        if snap is None:
            # 503 explicite : le detector doit traiter « pas de données » comme tel.
            return JSONResponse(
                status_code=503,
                content={"error": {"code": "no_fresh_data",
                                   "message": collector.last_error or "aucune collecte récente",
                                   "request_id": None}},
            )
        return snap.to_json()

    return app


async def _loop(collector: Collector, stop: asyncio.Event) -> None:
    prev_ok = True
    while not stop.is_set():
        snap = await collector.tick()
        if snap is None:
            collections_total.labels(result="failed").inc()
            if prev_ok:  # une seule ligne par épisode de panne, pas toutes les 15 s
                log.warning(f"Collecte impossible: {collector.last_error}")
            prev_ok = False
        else:
            collections_total.labels(result="ok").inc()
            feature_missing.set(len(snap.missing))
            if not prev_ok:
                log.info("Collecte rétablie")
            prev_ok = True
        try:
            await asyncio.wait_for(stop.wait(), timeout=collector.interval)
        except asyncio.TimeoutError:
            pass
