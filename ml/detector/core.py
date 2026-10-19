"""Cœur du detector : score ML -> décision -> AnomalyEvent -> POST remédiation.

Hiérarchie de décision (exigence R8 — la décision vient du MODÈLE) :

  1. DÉCIDEUR : `anomaly_score` (IsolationForest) >= `threshold`  -> anomalie
     (trigger="model"). C'est le chemin nominal et celui qui détecte les attaques
     multi-signaux ou subtiles.
  2. GARDE-FOU statistique (filet de sécurité, PAS le décideur) : si le score ML est
     sous le seuil mais qu'une feature s'écarte de la baseline de >= `guardrail_z`
     écarts-types (plancher 15, calibré sur les z maximaux de la baseline), on escalade quand
     même (trigger="guardrail"). Raison d'être : une IsolationForest dilue le score d'un
     pic extrême sur UNE seule feature (9 features, tirage uniforme) ; sans filet, un
     `req_per_s` à 100 sigma passerait sous le seuil. Voir README, section Limites.
  3. Le TYPE d'incident est ensuite étiqueté par `ml.shared.features.classify_incident`
     (heuristique de routage, pas de la détection).

Anti-spam : pendant qu'une anomalie persiste, un seul événement est émis par fenêtre de
`cooldown` secondes (la remédiation a son propre cooldown, contracts.md §4).
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass

import httpx

from resilience_common import AnomalyEvent, anomaly_score as anomaly_score_gauge, get_logger

from ml.detector.events import build_event
from ml.detector.model import LoadedModel
from ml.shared.features import classify_incident, zscores

SERVICE = "detector"
log = get_logger(SERVICE)

class RemediationClient:
    """POST authentifié des AnomalyEvent vers le moteur de remédiation (contracts.md §3)."""

    def __init__(self, url: str, token: str | None, timeout: float = 5.0,
                 retries: int = 3, backoff: float = 0.5,
                 transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.url, self.retries, self.backoff = url, retries, backoff
        self._token = token
        self._client = httpx.AsyncClient(timeout=timeout, transport=transport)

    @property
    def configured(self) -> bool:
        return bool(self._token)

    async def post_event(self, event: AnomalyEvent) -> bool:
        """True si le moteur a accepté l'événement (2xx). Le token n'est jamais loggé."""
        if not self._token:
            log.error("REMEDIATION_TOKEN absent : événement non envoyé")
            return False
        headers = {"Authorization": f"Bearer {self._token}"}
        body = event.model_dump(mode="json")
        for attempt in range(1, self.retries + 1):
            try:
                resp = await self._client.post(self.url, json=body, headers=headers)
                if resp.is_success:
                    return True
                log.warning(f"Remédiation a refusé l'événement (HTTP {resp.status_code}), "
                            f"tentative {attempt}/{self.retries}")
                if resp.status_code in (400, 401, 403, 422):
                    return False  # inutile de réessayer : erreur de contrat ou d'auth
            except httpx.HTTPError as exc:
                log.warning(f"Remédiation injoignable ({type(exc).__name__}), "
                            f"tentative {attempt}/{self.retries}")
            if attempt < self.retries:
                await asyncio.sleep(self.backoff * attempt)
        return False

    async def aclose(self) -> None:
        await self._client.aclose()


@dataclass
class Decision:
    score: float
    threshold: float
    is_anomaly: bool
    trigger: str | None  # "model" | "guardrail" | None
    event: AnomalyEvent | None = None  # renseigné si un événement a été construit
    posted: bool = False


class Detector:
    def __init__(self, model: LoadedModel, remediation: RemediationClient, *,
                 service: str = "payment-api", threshold: float | None = None,
                 cooldown: float = 60.0,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.model, self.remediation, self.service = model, remediation, service
        self.threshold = threshold if threshold is not None else model.threshold
        self.cooldown, self._clock = cooldown, clock
        self._last_emit: float | None = None
        self.last_decision: Decision | None = None

    async def process(self, vector: list[float]) -> Decision:
        score = self.model.score(vector)
        anomaly_score_gauge.labels(service=self.service).set(score)

        stats = self.model.stats
        z = zscores(vector, stats["mean"], stats["std"])
        max_z = max(z.values())  # seuls les écarts vers le HAUT caractérisent une attaque

        trigger: str | None = None
        if score >= self.threshold:
            trigger = "model"
        elif max_z >= self.model.guardrail_z:
            trigger = "guardrail"

        decision = Decision(score=score, threshold=self.threshold,
                            is_anomaly=trigger is not None, trigger=trigger)
        self.last_decision = decision
        if trigger is None:
            return decision

        if self._in_cooldown():
            return decision  # anomalie persistante déjà signalée

        event = build_event(
            service=self.service, score=score, threshold=self.threshold,
            incident_type=classify_incident(z), vector=vector, z=z,
        )
        decision.event = event
        log.warning(
            f"Anomalie {event.incident_type.value} (score {score:.3f} >= {self.threshold:.3f}, "
            f"déclencheur={trigger})",
            extra={"event": "anomaly_detected", "anomaly_score": round(score, 4)},
        )
        decision.posted = await self.remediation.post_event(event)
        if decision.posted:
            self._last_emit = self._clock()  # pas de cooldown si l'envoi a échoué : on réessaie
        return decision

    def _in_cooldown(self) -> bool:
        return self._last_emit is not None and (self._clock() - self._last_emit) < self.cooldown
