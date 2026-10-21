"""Limite de débit de /login, resserrable à chaud par la remédiation (tighten_rate_limit)."""

from __future__ import annotations

import math
import re
import threading
import time
from collections.abc import Callable

_RATE_RE = re.compile(r"^(\d+)/(second|minute|hour|day)$")
_PERIOD_SECONDS = {"second": 1, "minute": 60, "hour": 3600, "day": 86400}
FLOOR = 1  # on ne descend jamais sous 1 requête par période


class DynamicRateLimit:
    """Valeur de limite courante, lue par slowapi à chaque requête (callable)."""

    def __init__(self, baseline: str, restore_after_s: float = 0,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._baseline = self._parse(baseline)
        self._current = self._baseline
        self._lock = threading.Lock()
        # Un durcissement (remédiation) expire tout seul : l'attaque passée, les vrais utilisateurs
        # retrouvent la limite de base sans intervention humaine. 0 = pas d'expiration.
        self._restore_after_s = restore_after_s
        self._clock = clock
        self._tightened_at: float | None = None

    @staticmethod
    def _parse(value: str) -> tuple[int, str]:
        m = _RATE_RE.match(value)
        if not m:
            raise ValueError(f"limite invalide : {value!r}")
        return int(m.group(1)), m.group(2)

    def _expire(self) -> None:
        if (self._tightened_at is not None and self._restore_after_s
                and self._clock() - self._tightened_at >= self._restore_after_s):
            self._current, self._tightened_at = self._baseline, None

    @property
    def value(self) -> str:
        self._expire()
        count, unit = self._current
        return f"{count}/{unit}"

    @property
    def retry_after_seconds(self) -> int:
        return _PERIOD_SECONDS[self._current[1]]

    def __call__(self) -> str:  # slowapi appelle le provider sans argument
        return self.value

    def tighten(self, factor: float) -> tuple[str, str]:
        """Multiplie la limite par `factor` (0 < factor <= 1), plancher FLOOR. Renvoie (avant, après)."""
        if not 0 < factor <= 1:
            raise ValueError("factor doit être dans ]0, 1]")
        with self._lock:
            before = self.value
            count, unit = self._current
            self._current = (max(FLOOR, math.floor(count * factor)), unit)
            self._tightened_at = self._clock()
            return before, self.value

    def reset(self) -> tuple[str, str]:
        with self._lock:
            before = self.value
            self._current, self._tightened_at = self._baseline, None
            return before, self.value
