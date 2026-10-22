"""État public du service (`GET /api/v1/status`, #42) : cache TTL à vol unique.

Route sans auth exposée par le WAF : elle ne doit jamais devenir un vecteur d'amplification.
Au plus UNE vérification BDD par fenêtre, même sous rafale concurrente : un seul thread
rafraîchit, les autres servent la dernière valeur connue (ou attendent la toute première).
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime

from payment_api.schemas import ServiceStatusOut


class StatusCache:
    def __init__(
        self,
        probe: Callable[[], bool],
        ttl_s: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._probe, self._ttl, self._clock = probe, ttl_s, clock
        self._lock = threading.Lock()
        self._until = float("-inf")
        self._value: ServiceStatusOut | None = None

    def get(self) -> ServiceStatusOut:
        if self._clock() < self._until and self._value is not None:
            return self._value
        if self._value is None:
            self._lock.acquire()  # tout premier appel : rien à servir, on attend
        elif not self._lock.acquire(blocking=False):
            return self._value  # rafraîchissement déjà en cours (BDD lente) : valeur connue
        try:
            if self._clock() >= self._until or self._value is None:
                status = "ok" if self._probe() else "degraded"
                checked_at = datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
                self._value = ServiceStatusOut(status=status, checked_at=checked_at)
                self._until = self._clock() + self._ttl
            return self._value
        finally:
            self._lock.release()
