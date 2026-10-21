"""Moteur de remédiation : événement -> règle -> actions -> vérification -> clôture/escalade.

Cycle d'un incident (clé = incident_type + service) :

  admission   dédoublonnage (event_id, incident déjà en cours), cooldown
  tentative   actions de la règle DANS L'ORDRE ; après chaque action qui modifie l'état
              (et après la dernière) : boucle de vérification verify_tx
                verify OK -> incident clos (MTTD/MTTR, `remediation_verified`)
                verify KO -> action suivante
  échec       toutes les actions épuisées sans verify OK = 1 tentative consommée ;
              on attend le cooldown puis on recommence, jusqu'à max_attempts
  escalade    max_attempts atteint -> escalation (notify_operator, `remediation_failed`)

Garde-fous : cooldown, max_attempts, dry_run (aucune action qui modifie l'état), et le
verrou `_action_lock` qui sérialise les actions (jamais deux modifications simultanées).
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Awaitable, Callable

from actions import ActionContext, ActionError, ActionResult, build_action
from actions.base import Action
from config import Settings
from decision import DecisionTable, Rule
from journal import Journal
from models import IncomingEvent, utcnow
from resilience_common.metrics import mttd_seconds, mttr_seconds, remediation_actions_total
from timeline import Broker
from verify import Verifier

Clock = Callable[[], datetime]
Sleep = Callable[[float], Awaitable[None]]

MAX_GAUGE_INCIDENTS = 20  # borne la cardinalité du label incident_id des gauges MTTD/MTTR


@dataclass
class Submission:
    """Réponse d'admission d'un événement (retournée par POST /events)."""

    decision: str  # started | duplicate | replayed | cooldown
    incident_id: str | None
    dry_run: bool = False
    detail: str = ""


@dataclass
class _Incident:
    incident_id: str
    key: str
    event: IncomingEvent
    rule: Rule
    dry_run: bool
    detected_at: datetime
    first_action_at: datetime | None = None
    last_action_at: datetime | None = None
    attempts: int = 0
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class Services:
    """Dépendances externes injectables (mockées en test)."""

    http: Any
    docker: Any
    runner: Any
    verifier: Verifier


def incident_key(event: IncomingEvent) -> str:
    return f"{event.incident_type.value}:{event.service}"


class RemediationEngine:
    def __init__(self, *, table: DecisionTable, settings: Settings, journal: Journal, broker: Broker,
                 services: Services, log: logging.Logger, clock: Clock = utcnow,
                 sleep: Sleep = asyncio.sleep) -> None:
        self.table = table
        self.settings = settings
        self.journal = journal
        self.broker = broker
        self.services = services
        self.log = log
        self.clock = clock
        self._sleep = sleep
        self._active: dict[str, str] = {}  # clé d'incident -> incident_id en cours
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._action_lock = asyncio.Lock()
        self._gauge_ids: deque[str] = deque()

    # ------------------------------------------------------------------ propriétés
    @property
    def dry_run(self) -> bool:
        """Le dry-run peut être forcé par l'environnement, jamais désactivé par lui."""
        return self.settings.dry_run or self.table.defaults.dry_run

    # ------------------------------------------------------------------ admission
    async def handle_event(self, event: IncomingEvent) -> Submission:
        replay = self.journal.incident_for_event(event.event_id)
        if replay:  # le detector a rejoué le même événement (timeout réseau) : idempotent
            return Submission("replayed", replay, detail="événement déjà traité")

        key = incident_key(event)
        active = self._active.get(key)
        if active:
            self._emit(active, event.incident_type.value, "detection", "skipped",
                       "Événement dupliqué ignoré : incident déjà en cours", {"event_id": event.event_id})
            return Submission("duplicate", active, detail="incident déjà en cours")

        cooldown = self.table.defaults.cooldown_seconds
        last = self.journal.last_action_at(key)
        if last is not None:
            elapsed = (self.clock() - last).total_seconds()
            if elapsed < cooldown:
                prev = self.journal.last_incident_id(key)
                remaining = round(cooldown - elapsed, 1)
                msg = f"Cooldown actif : aucune ré-action sur {key} avant {remaining}s"
                self.log.info(msg, extra={"event": "remediation_action", "incident_id": prev})
                if prev:
                    self._emit(prev, event.incident_type.value, "decision", "skipped", msg,
                               {"event_id": event.event_id, "cooldown_remaining_s": remaining})
                return Submission("cooldown", prev, detail=msg)

        rule = self.table.rule_for(event.incident_type)
        incident_id = str(uuid.uuid4())
        inc = _Incident(incident_id, key, event, rule, self.dry_run, event.detected_at)
        self.journal.create_incident(
            incident_id=incident_id, key=key, incident_type=event.incident_type.value, service=event.service,
            event_id=event.event_id, event_json=event.model_dump_json(), detected_at=event.detected_at,
            dry_run=inc.dry_run,
        )
        self._active[key] = incident_id  # synchrone avec le contrôle ci-dessus : pas de course
        self.log.info(
            f"Remédiation démarrée : {key} (score={event.anomaly_score}, dry_run={inc.dry_run})",
            extra={"event": "remediation_started", "incident_id": incident_id,
                   "anomaly_score": event.anomaly_score},
        )
        self._emit(incident_id, event.incident_type.value, "detection", "info",
                   f"Anomalie détectée sur {event.service} : {event.incident_type.value}",
                   {"event_id": event.event_id, "source": event.source, "anomaly_score": event.anomaly_score,
                    "threshold": event.threshold, "service": event.service,
                    "features_top": [f.model_dump() for f in event.features_top]})
        self._emit(incident_id, event.incident_type.value, "decision", "info",
                   f"Règle sélectionnée : {' -> '.join(a.type for a in rule.actions)}"
                   + (" (DRY-RUN : aucune action destructive)" if inc.dry_run else ""),
                   {"actions": [a.model_dump() for a in rule.actions], "verify": rule.verify,
                    "dry_run": inc.dry_run, "max_attempts": self.table.defaults.max_attempts,
                    "cooldown_seconds": cooldown})
        task = asyncio.create_task(self._run(inc), name=f"incident-{incident_id}")
        self._tasks[incident_id] = task
        task.add_done_callback(lambda _t, i=incident_id: self._tasks.pop(i, None))
        return Submission("started", incident_id, dry_run=inc.dry_run)

    async def wait(self, incident_id: str) -> None:
        """Attend la fin d'un incident (tests, arrêt propre)."""
        task = self._tasks.get(incident_id)
        if task:
            await asyncio.shield(task)

    async def shutdown(self) -> None:
        for task in list(self._tasks.values()):
            task.cancel()
        await asyncio.gather(*self._tasks.values(), return_exceptions=True)

    # ------------------------------------------------------------------ déroulé
    async def _run(self, inc: _Incident) -> None:
        try:
            await self._remediate(inc)
        except asyncio.CancelledError:
            self.journal.finish(inc.incident_id, "interrupted", self.clock(), reason="arrêt du moteur")
            raise
        except Exception:  # noqa: BLE001 — un bug ne doit jamais laisser un incident sans issue
            self.log.exception("Erreur interne du moteur", extra={"incident_id": inc.incident_id})
            await self._escalate(inc, "erreur interne du moteur de remédiation")
        finally:
            self._active.pop(inc.key, None)

    async def _remediate(self, inc: _Incident) -> None:
        max_attempts = self.table.defaults.max_attempts
        cooldown = self.table.defaults.cooldown_seconds
        if inc.rule.verify_first and not inc.dry_run:
            if await self._verify(inc, 0, after="pré-contrôle (avant toute action)"):
                self._emit_inc(inc, "decision", "info",
                               "Service disponible : attaque contenue par les protections du WAF, aucune action",
                               {"verify_first": True})
                return self._close(inc)
        for attempt in range(1, max_attempts + 1):
            if attempt > 1 and inc.last_action_at is not None:
                wait = cooldown - (self.clock() - inc.last_action_at).total_seconds()
                if wait > 0:
                    self._emit_inc(inc, "decision", "info",
                                   f"Cooldown avant la tentative {attempt}/{max_attempts} ({wait:.0f}s)",
                                   {"attempt": attempt})
                    await self._sleep(wait)
            inc.attempts = attempt
            self.journal.set_attempts(inc.incident_id, attempt)
            outcome = await self._attempt(inc, attempt)
            if outcome == "verified":
                return self._close(inc)
            if outcome == "dry_run":
                return self._finish_dry_run(inc)
        await self._escalate(
            inc, f"verify_tx toujours KO après {max_attempts} tentative(s) : escalade (max_attempts)")

    async def _attempt(self, inc: _Incident, attempt: int) -> str:
        specs = inc.rule.actions
        for idx, spec in enumerate(specs):
            action = build_action(spec.type, spec.params)
            result = await self._execute(inc, attempt, action)
            if inc.dry_run:
                continue
            # On vérifie après toute action qui modifie l'état, et après la dernière.
            if result.ok and (action.mutating or idx == len(specs) - 1):
                if await self._verify(inc, attempt, after=spec.type):
                    return "verified"
        return "dry_run" if inc.dry_run else "failed"

    # ------------------------------------------------------------------ actions
    async def _execute(self, inc: _Incident, attempt: int, action: Action,
                       *, extra: dict[str, Any] | None = None) -> ActionResult:
        s = self.settings
        ctx = ActionContext(settings=s, http=self.services.http, docker=self.services.docker,
                            runner=self.services.runner, log=self.log, event=inc.event,
                            incident_id=inc.incident_id, dry_run=inc.dry_run, extra=extra or {})
        started = self.clock()
        first = inc.first_action_at is None
        if first:  # MTTD = détection -> première action
            inc.first_action_at = started
            mttd = max(0.0, (started - inc.detected_at).total_seconds())
            self._set_gauge(mttd_seconds, inc.incident_id, mttd)
        else:
            mttd = None
        inc.last_action_at = started
        self.journal.mark_action(inc.incident_id, started, first, mttd if first else None)
        self._emit_inc(inc, "action", "running", f"Action {action.type} en cours",
                       {"action": action.type, "params": action.params, "attempt": attempt})

        t0 = time.monotonic()
        try:
            if inc.dry_run and action.mutating:
                result = ActionResult(ok=True, dry_run=True, detail=await action.plan(ctx))
            else:
                async with self._action_lock:
                    result = await asyncio.wait_for(action.execute(ctx), timeout=s.action_timeout_s)
        except ActionError as exc:
            result = ActionResult(ok=False, detail=str(exc))
        except asyncio.TimeoutError:
            result = ActionResult(ok=False, detail=f"timeout après {s.action_timeout_s}s")
        except Exception as exc:  # noqa: BLE001 — détail volontairement limité au type (pas de fuite)
            self.log.exception("Action en erreur", extra={"incident_id": inc.incident_id})
            result = ActionResult(ok=False, detail=f"erreur inattendue ({type(exc).__name__})")
        duration_ms = int((time.monotonic() - t0) * 1000)

        label = "dry_run" if result.dry_run else ("success" if result.ok else "failure")
        remediation_actions_total.labels(action=action.type, result=label).inc()
        self.journal.add_action(inc.incident_id, attempt, started, action.type, action.params, label,
                                result.detail, duration_ms)
        self.log.log(
            logging.INFO if result.ok else logging.WARNING,
            f"action={action.type} result={label} dry_run={inc.dry_run} detail={result.detail}",
            extra={"event": "remediation_action", "incident_id": inc.incident_id},
        )
        status = "dry_run" if result.dry_run else ("ok" if result.ok else "failed")
        self._emit_inc(inc, "action", status, f"{action.type} : {result.detail}",
                       {"action": action.type, "attempt": attempt, "result": label,
                        "duration_ms": duration_ms, "changed": result.changed, **result.data})
        return result

    # ------------------------------------------------------------------ vérification
    async def _verify(self, inc: _Incident, attempt: int, *, after: str) -> bool:
        retries = max(1, self.settings.verify_retries)
        for i in range(1, retries + 1):
            res = await self.services.verifier.run()
            self.journal.add_verification(inc.incident_id, attempt, self.clock(), res.ok, res.rc, res.detail)
            self._emit_inc(inc, "verification", "ok" if res.ok else "ko",
                           f"verify_tx {'OK' if res.ok else 'KO'} après {after} (essai {i}/{retries})",
                           {"attempt": attempt, "try": i, "rc": res.rc, "detail": res.detail, "after": after})
            if res.ok:
                return True
            if i < retries:
                await self._sleep(self.settings.verify_interval_s)
        return False

    # ------------------------------------------------------------------ issues
    def _close(self, inc: _Incident) -> None:
        now = self.clock()
        mttr = max(0.0, (now - inc.detected_at).total_seconds())
        mttd = max(0.0, (inc.first_action_at - inc.detected_at).total_seconds()) if inc.first_action_at else None
        self._set_gauge(mttr_seconds, inc.incident_id, mttr)
        self.journal.finish(inc.incident_id, "closed", now, mttr=mttr)
        self.log.info(f"Remédiation vérifiée : retour à la normale (MTTD={mttd}s, MTTR={mttr:.2f}s)",
                      extra={"event": "remediation_verified", "incident_id": inc.incident_id})
        self._emit_inc(inc, "closure", "ok", f"Incident clos — service rétabli (MTTR {mttr:.1f}s)",
                       {"mttd_seconds": mttd, "mttr_seconds": mttr, "attempts": inc.attempts})

    def _finish_dry_run(self, inc: _Incident) -> None:
        self.journal.finish(inc.incident_id, "dry_run", self.clock(),
                            reason="dry-run : aucune action destructive exécutée, pas de vérification")
        self._emit_inc(inc, "closure", "dry_run",
                       "Dry-run terminé : actions journalisées, rien n'a été modifié", {})

    async def _escalate(self, inc: _Incident, reason: str) -> None:
        # notify_operator ne modifie pas le SI : exécuté même en dry-run.
        action = build_action(inc.rule.escalation, {})
        await self._execute(inc, inc.attempts, action, extra={"reason": reason})
        self.journal.finish(inc.incident_id, "escalated", self.clock(), reason=reason)
        self._emit_inc(inc, "escalation", "failed", f"Escalade : {reason}",
                       {"reason": reason, "attempts": inc.attempts})

    # ------------------------------------------------------------------ utilitaires
    def _emit_inc(self, inc: _Incident, phase: str, status: str, message: str, data: dict[str, Any]) -> None:
        self._emit(inc.incident_id, inc.event.incident_type.value, phase, status, message, data)

    def _emit(self, incident_id: str, incident_type: str, phase: str, status: str, message: str,
              data: dict[str, Any]) -> None:
        rec = self.journal.add_timeline(incident_id=incident_id, incident_type=incident_type, ts=self.clock(),
                                        phase=phase, status=status, message=message, data=data)
        self.broker.publish(rec)

    def _set_gauge(self, gauge: Any, incident_id: str, value: float) -> None:
        gauge.labels(incident_id=incident_id).set(value)
        if incident_id not in self._gauge_ids:
            self._gauge_ids.append(incident_id)
        while len(self._gauge_ids) > MAX_GAUGE_INCIDENTS:
            old = self._gauge_ids.popleft()
            for g in (mttd_seconds, mttr_seconds):
                try:
                    g.remove(old)
                except KeyError:
                    pass
