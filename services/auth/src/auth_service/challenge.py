"""État serveur de l'authentification à étapes du back-office (consigne additionnelle 1).

Deux stores en mémoire, par processus (cohérent avec le rate-limit auth — limite assumée,
cf. README ; option Redis documentée) :

- `ChallengeStore` : le fil identifiant → visage → mot de passe. Un `challenge_id` est **retiré
  atomiquement** (`take`) au début de chaque étape puis réinséré si l'étape avance — deux requêtes
  concurrentes ne peuvent donc pas réutiliser le même challenge (pas de TOCTOU). TTL court, purge
  des expirés et plafond de taille (anti-DoS mémoire).
- `LockoutStore` : le verrouillage « 1 reprise puis 5 min » par couple (username, ip). Un échec
  d'accès = visage non reconnu OU mot de passe erroné (compteur unifié), avec **fenêtre glissante**
  (un échec isolé et ancien ne verrouille pas). Protégé par un verrou ; purge des entrées expirées.

L'horloge est injectable (`clock`) pour des tests déterministes (TTL, expiration du blocage).
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from enum import Enum
from math import ceil
from uuid import uuid4

#: Plafond de sécurité sur le nombre de challenges simultanés (anti-DoS mémoire).
MAX_CHALLENGES = 10_000
#: Plafond de sécurité sur le nombre d'entrées de verrouillage suivies.
MAX_LOCKS = 10_000


class ChallengeStep(str, Enum):
    FACE = "face"
    PASSWORD = "password"


@dataclass
class Challenge:
    challenge_id: str
    username: str
    step: ChallengeStep
    expires_at: float


class ChallengeStore:
    def __init__(self, ttl_seconds: float, clock=time.monotonic, max_size: int = MAX_CHALLENGES) -> None:
        self._ttl = ttl_seconds
        self._clock = clock
        self._max_size = max_size
        self._items: dict[str, Challenge] = {}
        self._lock = threading.Lock()

    def _purge(self, now: float) -> None:
        expired = [cid for cid, c in self._items.items() if now >= c.expires_at]
        for cid in expired:
            del self._items[cid]

    def create(self, username: str, *, step: ChallengeStep = ChallengeStep.FACE) -> Challenge:
        now = self._clock()
        challenge = Challenge(
            challenge_id=uuid4().hex, username=username, step=step, expires_at=now + self._ttl
        )
        with self._lock:
            self._purge(now)
            if len(self._items) >= self._max_size:
                # Plafond atteint : on laisse tomber l'entrée la plus ancienne plutôt que de croître.
                oldest = min(self._items, key=lambda c: self._items[c].expires_at)
                del self._items[oldest]
            self._items[challenge.challenge_id] = challenge
        return challenge

    def take(self, challenge_id: str) -> Challenge | None:
        """Retire ET renvoie le challenge (atomique). None s'il est inconnu ou expiré.

        Garantit l'usage unique par étape : deux requêtes concurrentes avec le même id,
        une seule obtient le challenge, l'autre reçoit None.
        """
        now = self._clock()
        with self._lock:
            challenge = self._items.pop(challenge_id, None)
        if challenge is None or now >= challenge.expires_at:
            return None
        return challenge

    def put(self, challenge: Challenge) -> None:
        """Réinsère un challenge retiré par `take` (ex. étape inattendue : on ne le détruit pas)."""
        with self._lock:
            self._items[challenge.challenge_id] = challenge

    def reinsert_for_password(self, challenge: Challenge) -> None:
        """Visage reconnu : repasse le challenge à l'étape mot de passe, TTL rafraîchi."""
        challenge.step = ChallengeStep.PASSWORD
        challenge.expires_at = self._clock() + self._ttl
        self.put(challenge)


@dataclass
class _Lock:
    failures: int = 0
    last_failure_at: float = 0.0
    locked_until: float | None = None


@dataclass
class LockoutStatus:
    locked: bool
    retry_after: int = 0
    attempts_left: int = 0
    just_locked: bool = False  # True seulement sur la transition verrou (métrique/journal)


class LockoutStore:
    """Verrouillage par (username, ip) : `max_attempts` échecs puis `lockout_seconds` de blocage.

    Fenêtre glissante `failure_window_seconds` : un échec plus ancien que la fenêtre est oublié.
    """

    def __init__(
        self,
        max_attempts: int,
        lockout_seconds: float,
        clock=time.monotonic,
        failure_window_seconds: float = 900.0,
        max_size: int = MAX_LOCKS,
    ) -> None:
        self._max = max_attempts
        self._lockout = lockout_seconds
        self._clock = clock
        self._window = failure_window_seconds
        self._max_size = max_size
        self._locks: dict[tuple[str, str], _Lock] = {}
        self._lock = threading.Lock()

    def _key(self, username: str, ip: str | None) -> tuple[str, str]:
        return (username, ip or "unknown")

    def _purge(self, now: float) -> None:
        stale = [
            k
            for k, lock in self._locks.items()
            if (lock.locked_until is None or now >= lock.locked_until)
            and now - lock.last_failure_at > self._window
        ]
        for k in stale:
            del self._locks[k]

    def status(self, username: str, ip: str | None) -> LockoutStatus:
        key = self._key(username, ip)
        now = self._clock()
        with self._lock:
            lock = self._locks.get(key)
            if lock is None:
                return LockoutStatus(locked=False, attempts_left=self._max)
            if lock.locked_until is not None:
                remaining = lock.locked_until - now
                if remaining > 0:
                    return LockoutStatus(locked=True, retry_after=ceil(remaining))
                del self._locks[key]  # blocage expiré : on repart à zéro
                return LockoutStatus(locked=False, attempts_left=self._max)
            if now - lock.last_failure_at > self._window:
                del self._locks[key]  # échecs trop anciens : oubliés (fenêtre glissante)
                return LockoutStatus(locked=False, attempts_left=self._max)
            return LockoutStatus(locked=False, attempts_left=max(self._max - lock.failures, 0))

    def record_failure(self, username: str, ip: str | None) -> LockoutStatus:
        key = self._key(username, ip)
        now = self._clock()
        with self._lock:
            self._purge(now)
            lock = self._locks.get(key)
            if lock is not None and lock.locked_until is not None and lock.locked_until - now > 0:
                # Déjà bloqué : pas de ré-incrément ni de nouvelle transition.
                return LockoutStatus(locked=True, retry_after=ceil(lock.locked_until - now))
            if lock is None or now - lock.last_failure_at > self._window:
                lock = _Lock()  # nouvelle série (jamais vu, ou fenêtre expirée)
                if len(self._locks) >= self._max_size:
                    oldest = min(self._locks, key=lambda k: self._locks[k].last_failure_at)
                    del self._locks[oldest]
                self._locks[key] = lock
            lock.failures += 1
            lock.last_failure_at = now
            if lock.failures >= self._max:
                lock.locked_until = now + self._lockout
                return LockoutStatus(locked=True, retry_after=ceil(self._lockout), just_locked=True)
            return LockoutStatus(locked=False, attempts_left=max(self._max - lock.failures, 0))

    def reset(self, username: str, ip: str | None) -> None:
        with self._lock:
            self._locks.pop(self._key(username, ip), None)
