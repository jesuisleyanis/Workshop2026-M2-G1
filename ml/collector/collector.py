"""Collector : interroge l'API Prometheus et construit le vecteur de features.

Une collecte = 9 requêtes PromQL instantanées (une par feature de
`ml.shared.features.FEATURE_NAMES`). Le résultat est un `Snapshot` conservé en
mémoire et exposé au detector par l'endpoint GET /api/v1/features (voir app.py).

Gestion de l'absence de données (point dur de la fiche) :
  * Prometheus injoignable / HTTP en erreur -> la collecte échoue (`CollectError`),
    l'ancien snapshot est CONSERVÉ mais devient « périmé » (stale) : le detector ne
    score jamais une donnée périmée ;
  * série absente ou NaN pour UNE feature (ex. aucun trafic -> ratio 0/0, pas encore
    d'erreur DB) -> valeur 0.0 et la feature est listée dans `missing` (traçabilité) ;
  * TOUTES les features absentes -> pas de snapshot (`NoData`), jamais un vecteur
    de zéros qui passerait pour du trafic normal.
"""

from __future__ import annotations

import asyncio
import math
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

import httpx

from ml.shared.features import FEATURE_NAMES, WINDOW_SECONDS, vector_from_dict


class CollectError(RuntimeError):
    """Prometheus injoignable ou réponse invalide."""


class NoData(RuntimeError):
    """Prometheus répond mais aucune des features n'a de valeur."""


def build_queries(window: str = "30s") -> dict[str, str]:
    """Requêtes PromQL par feature (noms de métriques : docs/contracts.md §2).

    `window` est la fenêtre des `rate()`. Le contrat parle d'une fenêtre de 15 s ;
    rate() exige >= 2 échantillons dans la fenêtre, donc 30 s par défaut pour un scrape
    de 15 s (ajustable via PROM_RATE_WINDOW si le scrape est plus fréquent).
    """
    w = window
    total = f"sum(rate(resilience_http_requests_total[{w}]))"
    return {
        "req_per_s": total,
        "p95_latency_ms": (
            "1000 * histogram_quantile(0.95, "
            f"sum by (le) (rate(resilience_http_request_duration_seconds_bucket[{w}])))"
        ),
        "ratio_4xx": (
            f'sum(rate(resilience_http_requests_total{{status=~"4.."}}[{w}])) / {total}'
        ),
        "ratio_5xx": (
            f'sum(rate(resilience_http_requests_total{{status=~"5.."}}[{w}])) / {total}'
        ),
        "auth_failed_per_s": (
            f'sum(rate(resilience_auth_logins_total{{result="failed"}}[{w}]))'
        ),
        "waf_blocked_per_s": f"sum(rate(resilience_waf_blocked_total[{w}]))",
        # cAdvisor : % d'un coeur pour le conteneur le plus chargé
        "cpu_pct_max": (
            f'100 * max(rate(container_cpu_usage_seconds_total{{name!=""}}[{w}]))'
        ),
        # cAdvisor : % de la limite mémoire pour le conteneur le plus chargé
        # (seuls les conteneurs avec limite définie comptent)
        "mem_pct_max": (
            "100 * max(container_memory_working_set_bytes{name!=\"\"} "
            "/ (container_spec_memory_limit_bytes{name!=\"\"} > 0))"
        ),
        "db_errors_per_s": f"sum(rate(resilience_db_errors_total[{w}]))",
    }


@dataclass(frozen=True)
class Snapshot:
    """Un vecteur de features horodaté."""

    vector: list[float]
    ts: datetime
    missing: tuple[str, ...] = ()
    monotonic: float = field(default_factory=time.monotonic, compare=False)

    def to_json(self) -> dict:
        return {
            "feature_names": list(FEATURE_NAMES),
            "vector": self.vector,
            "ts": self.ts.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "missing": list(self.missing),
            "window_seconds": WINDOW_SECONDS,
        }


class PrometheusClient:
    """Client minimal de l'API HTTP Prometheus (/api/v1/query)."""

    def __init__(self, base_url: str, timeout: float = 5.0,
                 transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"), timeout=timeout, transport=transport
        )

    async def query_scalar(self, promql: str) -> float | None:
        """Valeur scalaire d'une requête instantanée ; None si aucune série / NaN."""
        try:
            resp = await self._client.get("/api/v1/query", params={"query": promql})
            resp.raise_for_status()
            body = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise CollectError(f"Prometheus injoignable ou réponse invalide: {exc}") from exc
        if body.get("status") != "success":
            raise CollectError(f"Prometheus status={body.get('status')!r}: {body.get('error')}")
        result = body.get("data", {}).get("result", [])
        if not result:
            return None
        try:
            value = float(result[0]["value"][1])
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise CollectError(f"réponse Prometheus inattendue: {result[0]!r}") from exc
        return value if math.isfinite(value) else None

    async def is_up(self) -> bool:
        try:
            resp = await self._client.get("/-/ready")
            return resp.status_code == 200
        except httpx.HTTPError:
            return False

    async def aclose(self) -> None:
        await self._client.aclose()


class Collector:
    """Boucle de collecte + dernier snapshot en mémoire."""

    def __init__(self, prom: PrometheusClient, queries: dict[str, str] | None = None,
                 interval: float = 15.0, stale_after: float | None = None) -> None:
        self.prom = prom
        self.queries = queries or build_queries()
        self.interval = interval
        self.stale_after = stale_after if stale_after is not None else 3 * interval
        self.latest: Snapshot | None = None
        self.last_error: str | None = None
        self.collections_ok = 0
        self.collections_failed = 0

    async def collect(self) -> Snapshot:
        """Une collecte. Lève CollectError (Prometheus KO) ou NoData (rien à lire)."""
        names = list(FEATURE_NAMES)
        values = await asyncio.gather(*(self.prom.query_scalar(self.queries[n]) for n in names))
        raw = dict(zip(names, values))
        missing = tuple(n for n in names if raw[n] is None)
        if len(missing) == len(names):
            raise NoData("aucune série disponible pour les 9 features")
        vector = vector_from_dict({n: (0.0 if v is None else v) for n, v in raw.items()})
        return Snapshot(vector=vector, ts=datetime.now(timezone.utc), missing=missing)

    async def tick(self) -> Snapshot | None:
        """Collecte + mise à jour de l'état ; ne lève jamais (la boucle doit survivre)."""
        try:
            self.latest = await self.collect()
            self.last_error = None
            self.collections_ok += 1
            return self.latest
        except (CollectError, NoData) as exc:
            self.last_error = str(exc)
            self.collections_failed += 1
            return None

    def fresh(self) -> Snapshot | None:
        """Le dernier snapshot s'il est assez récent, sinon None."""
        snap = self.latest
        if snap is None or (time.monotonic() - snap.monotonic) > self.stale_after:
            return None
        return snap
