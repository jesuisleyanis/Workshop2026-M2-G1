"""Authentification à étapes du back-office (consigne additionnelle 1, contrat §5.2).

Orchestre identifiant → visage (via le service face-id) → mot de passe, avec verrouillage
et pilotage de la LED. `auth` est le seul à décider de l'accès : face-id ne renvoie que
match/no-match, et le mot de passe + le rôle privilégié restent obligatoires (pas de bypass).

Le verrouillage est contrôlé à **chaque** étape (un challenge pré-créé ne permet pas de
contourner le blocage). Les challenges sont retirés atomiquement (`take`) : pas de rejeu ni de
TOCTOU. Les routes sont rate-limitées comme `/login`.

Les dépendances externes sont injectables (vérificateur de visage, notifieur LED, horloge)
pour des tests déterministes sans réseau ni matériel.
"""

from __future__ import annotations

import logging
import secrets
from typing import Protocol

from fastapi import FastAPI, Request
from resilience_common.metrics import (
    auth_face_steps_total,
    auth_lockouts_total,
    auth_logins_total,
    led_publish_total,
)
from resilience_db.models import User
from resilience_db.passwords import DUMMY_HASH, verify_password
from slowapi import Limiter
from sqlalchemy import select

from auth_service.challenge import (
    POSES,
    Challenge,
    ChallengeStep,
    ChallengeStore,
    CooldownStore,
    LockoutStore,
)
from auth_service.config import Settings
from auth_service.face_client import FaceUnavailable
from auth_service.observability import ApiError, client_ip_var, log_event
from auth_service.schemas import (
    FaceRequest,
    FaceResponse,
    IdentifyRequest,
    IdentifyResponse,
    PasswordRequest,
    SteppedTokenOut,
)
from auth_service.security import create_access_token

PRIVILEGED_ROLES = frozenset({"operator", "admin"})

# États sémantiques de la LED (contrat §5.3).
LED_IDLE = "idle"
LED_RECOGNIZED = "recognized"
LED_AUTH_OK = "auth_ok"
LED_AUTH_FAIL = "auth_fail"
LED_NOT_RECOGNIZED = "not_recognized"


class FaceVerifier(Protocol):
    def verify(self, username: str, frames: list[dict]) -> bool:
        """True si les 3 frames correspondent à l'identifiant. Lève FaceUnavailable si face-id
        est injoignable (ré-exporté ici depuis `face_client`)."""
        ...


class LedNotifier(Protocol):
    def publish(self, state: str, challenge_id: str | None) -> None: ...


class LogLedNotifier:
    """Notifieur LED par défaut : journalise l'état (le backend MQTT réel arrive au lot L5-2).

    **Fail-open** : une publication qui échoue n'interrompt jamais l'authentification
    (la LED est un témoin, pas un facteur).
    """

    def __init__(self, log: logging.Logger) -> None:
        self._log = log

    def publish(self, state: str, challenge_id: str | None) -> None:
        try:
            log_event(self._log, logging.INFO, "led_state_published", f"LED -> {state}")
            led_publish_total.labels(state, "ok").inc()
        except Exception as exc:  # noqa: BLE001 - fail-open : ne jamais bloquer l'auth
            led_publish_total.labels(state, "error").inc()
            log_event(
                self._log, logging.WARNING, "led_publish_failed", f"LED publish failed: {exc}"
            )


def add_backoffice_auth(
    app: FastAPI,
    *,
    settings: Settings,
    session_factory,
    log: logging.Logger,
    face_verifier: FaceVerifier,
    led: LedNotifier,
    challenges: ChallengeStore,
    lockouts: LockoutStore,
    cooldowns: CooldownStore,
    limiter: Limiter,
) -> None:
    """Ajoute les 3 routes de l'authentification à étapes du back-office."""

    rate = settings.backoffice_rate_limit

    def _load_user(username: str) -> User | None:
        with session_factory() as session:
            return session.scalar(select(User).where(User.username == username))

    def _locked_response(username: str, ip: str | None, retry_after: int) -> ApiError:
        led.publish(LED_IDLE, None)
        log_event(
            log, logging.WARNING, "auth_locked_out",
            f"Back-office access locked for {username}", http_status=429, user=username,
        )
        return ApiError(429, "locked_out", "Too many failed attempts", {"Retry-After": str(retry_after)})

    def _record_and_maybe_lock(username: str, ip: str | None) -> int:
        """Enregistre un échec ; incrémente la métrique/journal SEULEMENT sur la transition."""
        outcome = lockouts.record_failure(username, ip)
        if outcome.just_locked:
            auth_lockouts_total.inc()
            log_event(
                log, logging.WARNING, "auth_locked_out",
                f"Back-office access locked for {username}", user=username,
            )
        return outcome.attempts_left

    @app.post("/api/v1/auth/identify", response_model=IdentifyResponse)
    @limiter.limit(rate)
    def identify(request: Request, body: IdentifyRequest):
        ip = client_ip_var.get()
        status = lockouts.status(body.username, ip)
        if status.locked:
            raise _locked_response(body.username, ip, status.retry_after)
        wait, reason = cooldowns.remaining(ip)
        if wait > 0:
            log_event(
                log, logging.WARNING, "auth_cooldown",
                f"Cooldown active ({reason}), retry in {wait}s", http_status=429, user=body.username,
            )
            raise ApiError(429, "cooldown", "Please wait", {"Retry-After": str(wait)})
        # Mode dégradé documenté (répétitions de démo) : sans facteur visage, on va direct au mdp.
        if settings.backoffice_face_required:
            step = ChallengeStep.FACE
            # Ordre des poses tiré côté serveur (CSPRNG) : une photo/vidéo préparée ne suffit pas.
            poses = tuple(secrets.SystemRandom().sample(POSES, 3))
        else:
            step, poses = ChallengeStep.PASSWORD, ()
        challenge = challenges.create(body.username, step=step, poses=poses)
        led.publish(LED_IDLE, challenge.challenge_id)
        # Toujours 200 hors blocage : ne révèle pas l'existence du compte (anti-énumération).
        log_event(
            log, logging.INFO, "auth_identify_started",
            f"Identify step started for {body.username}", http_status=200, user=body.username,
        )
        return IdentifyResponse(
            challenge_id=challenge.challenge_id,
            step=challenge.step.value,
            expires_in=settings.backoffice_challenge_ttl,
            camera=settings.backoffice_face_required,
            poses=list(challenge.poses),
        )

    def _take_for_step(challenge_id: str, expected: ChallengeStep) -> Challenge:
        challenge = challenges.take(challenge_id)
        if challenge is None:
            raise ApiError(400, "challenge_invalid", "Unknown or expired challenge")
        ip = client_ip_var.get()
        status = lockouts.status(challenge.username, ip)
        if status.locked:
            # Blocage vérifié aussi ici : un challenge pré-créé ne contourne pas le verrou.
            raise _locked_response(challenge.username, ip, status.retry_after)
        if challenge.step is not expected:
            challenges.put(challenge)  # étape inattendue : on ne détruit pas le challenge
            raise ApiError(409, "wrong_step", f"{expected.value} step is not expected now")
        return challenge

    @app.post("/api/v1/auth/face", response_model=FaceResponse)
    @limiter.limit(rate)
    def face(request: Request, body: FaceRequest):
        ip = client_ip_var.get()
        challenge = _take_for_step(body.challenge_id, ChallengeStep.FACE)

        frames = [{"pose": f.pose, "image_b64": f.image_b64} for f in body.frames]
        if [f["pose"] for f in frames] != list(challenge.poses):
            # Poses dans le mauvais ordre : refus sans appeler face-id (anti-rejeu de captures).
            recognized = False
        else:
            try:
                recognized = face_verifier.verify(challenge.username, frames)
            except FaceUnavailable as exc:
                # Back-office inaccessible par conception si le facteur visage est indisponible.
                raise ApiError(503, "face_service_unavailable", "Face service unavailable") from exc

        if recognized:
            challenges.reinsert_for_password(challenge)
            auth_face_steps_total.labels(result="recognized").inc()
            led.publish(LED_RECOGNIZED, challenge.challenge_id)
            log_event(
                log, logging.INFO, "auth_face_recognized",
                f"Face recognized for {challenge.username}", http_status=200, user=challenge.username,
            )
            left = lockouts.status(challenge.username, ip).attempts_left
            return FaceResponse(
                recognized=True, step=ChallengeStep.PASSWORD.value, attempts_left=left, cooldown=0
            )

        # Non reconnu : challenge déjà retiré (consommé), échec compté, LED rouge fixe.
        auth_face_steps_total.labels(result="rejected").inc()
        led.publish(LED_NOT_RECOGNIZED, None)
        log_event(
            log, logging.WARNING, "auth_face_rejected",
            f"Face not recognized for {challenge.username}", http_status=200, user=challenge.username,
        )
        left = _record_and_maybe_lock(challenge.username, ip)
        cooldowns.start(ip, settings.backoffice_reject_cooldown, "not_recognized")
        # step "identify" : on repart à la saisie de l'identifiant (contrat §5.2).
        return FaceResponse(
            recognized=False,
            step="identify",
            attempts_left=left,
            cooldown=settings.backoffice_reject_cooldown,
        )

    @app.post("/api/v1/auth/password", response_model=SteppedTokenOut)
    @limiter.limit(rate)
    def password(request: Request, body: PasswordRequest):
        ip = client_ip_var.get()
        challenge = _take_for_step(body.challenge_id, ChallengeStep.PASSWORD)

        user = _load_user(challenge.username)
        valid = verify_password(body.password, user.password_hash if user else DUMMY_HASH)

        if user is None or not valid:
            auth_logins_total.labels(result="failed").inc()
            led.publish(LED_AUTH_FAIL, None)
            log_event(
                log, logging.WARNING, "auth_login_failed",
                f"Invalid password for {challenge.username}", http_status=401, user=challenge.username,
            )
            _record_and_maybe_lock(challenge.username, ip)
            cooldowns.start(ip, settings.backoffice_fail_cooldown, "auth_fail")
            raise ApiError(
                401, "invalid_credentials", "Invalid credentials",
                {"Retry-After": str(settings.backoffice_fail_cooldown)},
            )

        if user.role not in PRIVILEGED_ROLES:
            # Identifiants valides mais rôle non autorisé pour le back-office (pas un brute-force
            # : on ne compte pas d'échec de verrouillage). LED rouge, challenge déjà consommé.
            led.publish(LED_AUTH_FAIL, None)
            log_event(
                log, logging.WARNING, "auth_login_failed",
                f"Role '{user.role}' not authorized for back-office ({user.username})",
                http_status=403, user=user.username,
            )
            raise ApiError(403, "role_not_authorized", "Account not authorized for the back-office")

        # Succès complet : jeton émis (rôle en claim), verrou réinitialisé, LED vert fixe.
        lockouts.reset(challenge.username, ip)
        token, expires_in = create_access_token(user.username, settings.jwt_secret, role=user.role)
        auth_logins_total.labels(result="success").inc()
        led.publish(LED_AUTH_OK, None)
        log_event(
            log, logging.INFO, "auth_login_success",
            f"Back-office login for {user.username}", http_status=200, user=user.username,
        )
        return SteppedTokenOut(access_token=token, expires_in=expires_in, role=user.role)
