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
import contextlib
import math
import time
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime

import httpx

from ml.shared.features import FEATURE_NAMES, WINDOW_SECONDS, vector_from_dict


class CollectError(RuntimeError):
    """Prometheus injoignable ou réponse invalide."""


class NoData(RuntimeError):
    """Prometheus répond mais aucune des features n'a de valeur."""


#: Services compose dont la charge (CPU, mémoire) compte comme signal : ceux que les attaques
#: visent. Label posé par Docker et exposé par cAdvisor.
PLATFORM_SERVICES = ("waf", "front", "payment-api", "auth", "postgres")
PLATFORM = f'container_label_com_docker_compose_service=~"{"|".join(PLATFORM_SERVICES)}"'


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
        # Tentatives de login REFUSÉES : mauvais mot de passe ET refus du rate-limit. Sans le
        # second terme, une attaque par force brute retombe à ~0 dès que le rate-limit répond 429
        # (compteur à part, resilience_auth_rate_limited_total) et serait routée en service_flood.
        # `or vector(0)` : un compteur sans série (aucun échec encore) ne masque pas l'autre.
        "auth_failed_per_s": (
            f'(sum(rate(resilience_auth_logins_total{{result="failed"}}[{w}])) or vector(0))'
            f" + (sum(rate(resilience_auth_rate_limited_total[{w}])) or vector(0))"
        ),
        "waf_blocked_per_s": f"sum(rate(resilience_waf_blocked_total[{w}]))",
        # cAdvisor : % d'un coeur pour le conteneur de la PLATEFORME le plus chargé. Pas
        # l'observabilité (cAdvisor, Prometheus, Grafana) : leur charge propre n'est pas un
        # signal d'attaque et dominait la feature (compactions, cAdvisor à 92 % de sa limite).
        "cpu_pct_max": (
            f"100 * max(rate(container_cpu_usage_seconds_total{{{PLATFORM}}}[{w}]))"
        ),
        # cAdvisor : % de la limite mémoire pour le conteneur de la plateforme le plus chargé
        # (seuls les conteneurs avec limite définie comptent)
        "mem_pct_max": (
            f"100 * max(container_memory_working_set_bytes{{{PLATFORM}}} "
            f"/ (container_spec_memory_limit_bytes{{{PLATFORM}}} > 0))"
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
    seq: int = 0  # numéro de collecte (croissant) : le detector ne score jamais deux fois le même

    def to_json(self) -> dict:
        return {
            "feature_names": list(FEATURE_NAMES),
            "vector": self.vector,
            "ts": self.ts.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "missing": list(self.missing),
            "window_seconds": WINDOW_SECONDS,
            "seq": self.seq,
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
        self.seq = 0
        # Réveille les attentes longues (detector) à chaque collecte ; créée à la demande car une
        # Condition asyncio est liée à la boucle qui l'utilise (une seule en production).
        self._new: asyncio.Condition | None = None
        self._new_loop: asyncio.AbstractEventLoop | None = None

    async def collect(self) -> Snapshot:
        """Une collecte. Lève CollectError (Prometheus KO) ou NoData (rien à lire)."""
        names = list(FEATURE_NAMES)
        values = await asyncio.gather(*(self.prom.query_scalar(self.queries[n]) for n in names))
        raw = dict(zip(names, values, strict=False))
        missing = tuple(n for n in names if raw[n] is None)
        if len(missing) == len(names):
            raise NoData("aucune série disponible pour les 9 features")
        vector = vector_from_dict({n: (0.0 if v is None else v) for n, v in raw.items()})
        return Snapshot(vector=vector, ts=datetime.now(UTC), missing=missing)

    async def tick(self) -> Snapshot | None:
        """Collecte + mise à jour de l'état ; ne lève jamais (la boucle doit survivre)."""
        try:
            snap = await self.collect()
            self.seq += 1
            self.latest = replace(snap, seq=self.seq)
            self.last_error = None
            self.collections_ok += 1
            cond = self._condition()
            async with cond:
                cond.notify_all()
            return self.latest
        except (CollectError, NoData) as exc:
            self.last_error = str(exc)
            self.collections_failed += 1
            return None

    async def wait_newer(self, after: int, timeout: float) -> Snapshot | None:
        """Attente longue : le premier snapshot frais de numéro > `after`, ou après `timeout`
        secondes le dernier snapshot frais (éventuellement le même). Supprime la latence de
        relève côté detector : il est servi dès la fin de la collecte."""
        if self.seq <= after:
            cond = self._condition()
            async with cond:
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(cond.wait_for(lambda: self.seq > after), timeout)
        return self.fresh()

    def _condition(self) -> asyncio.Condition:
        loop = asyncio.get_running_loop()
        if self._new is None or self._new_loop is not loop:
            self._new, self._new_loop = asyncio.Condition(), loop
        return self._new

    def fresh(self) -> Snapshot | None:
        """Le dernier snapshot s'il est assez récent, sinon None."""
        snap = self.latest
        if snap is None or (time.monotonic() - snap.monotonic) > self.stale_after:
            return None
        return snap
