"""Limite de débit de /login, resserrable à chaud par la remédiation (tighten_rate_limit)."""

from __future__ import annotations

import math
import re
import threading

_RATE_RE = re.compile(r"^(\d+)/(second|minute|hour|day)$")
_PERIOD_SECONDS = {"second": 1, "minute": 60, "hour": 3600, "day": 86400}
FLOOR = 1  # on ne descend jamais sous 1 requête par période


class DynamicRateLimit:
    """Valeur de limite courante, lue par slowapi à chaque requête (callable)."""

    def __init__(self, baseline: str) -> None:
        self._baseline = self._parse(baseline)
        self._current = self._baseline
        self._lock = threading.Lock()

    @staticmethod
    def _parse(value: str) -> tuple[int, str]:
        m = _RATE_RE.match(value)
        if not m:
            raise ValueError(f"limite invalide : {value!r}")
        return int(m.group(1)), m.group(2)

    @property
    def value(self) -> str:
        count, unit = self._current
        return f"{count}/{unit}"

    @property
    def retry_after_seconds(self) -> int:
        return _PERIOD_SECONDS[self._current[1]]

    def __call__(self) -> str:  # slowapi appelle le provider sans argument
        return self.value

    @property
    def _units(self) -> int:
        # Budget en « unités » divisible par toute limite courante possible (1..baseline) :
        # ppcm(1..baseline). Le coût d'un essai est alors exact, jamais un arrondi.
        count = self._baseline[0]
        if count <= 60:  # ppcm(1..60) ~ 1e25 : entier Python, stockage mémoire de slowapi
            return math.lcm(*range(1, count + 1))
        return count * 1000  # au-delà : au plus 1 essai de moins que la limite courante

    @property
    def baseline_value(self) -> str:
        """Chaîne de limite FIXE passée à slowapi : la clé du compteur (qui inclut le montant de
        la limite) ne change donc jamais, et un resserrement ne remet aucun compteur à zéro."""
        return f"{self._units}/{self._baseline[1]}"

    def cost(self, _request=None) -> int:
        """Coût d'un essai : budget / limite courante, entier exact -> exactement `current` essais
        par période (resserrer augmente le coût au lieu de changer la clé du compteur)."""
        return -(-self._units // self._current[0])  # plafond entier (pas de float à 1e25)

    def tighten(self, factor: float) -> tuple[str, str]:
        """Multiplie la limite par `factor` (0 < factor <= 1), plancher FLOOR. Renvoie (avant, après)."""
        if not 0 < factor <= 1:
            raise ValueError("factor doit être dans ]0, 1]")
        with self._lock:
            before = self.value
            count, unit = self._current
            self._current = (max(FLOOR, math.floor(count * factor)), unit)
            return before, self.value

    def reset(self) -> tuple[str, str]:
        with self._lock:
            before = self.value
            self._current = self._baseline
            return before, self.value
