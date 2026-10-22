"""Configuration du service auth, lue depuis l'environnement (aucun secret en dur)."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

from resilience_db.config import read_secret

from auth_service.observability import parse_trusted_proxies

SERVICE_NAME = "auth"
MIN_SECRET_LENGTH = 32
_RATE_RE = re.compile(r"^(\d+)/(second|minute|hour|day)$")


def _bool(name: str, default: bool) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in {"1", "true", "yes"}


def _read_face_token() -> str:
    """Token pour face-id (optionnel) : FACE_INTERNAL_TOKEN_FILE puis FACE_INTERNAL_TOKEN."""
    from pathlib import Path

    file_var = os.environ.get("FACE_INTERNAL_TOKEN_FILE")
    if file_var and Path(file_var).is_file():
        return Path(file_var).read_text().strip()
    return os.environ.get("FACE_INTERNAL_TOKEN", "")


@dataclass(frozen=True)
class Settings:
    jwt_secret: str
    internal_token: str
    login_rate_limit: str = "10/minute"
    register_rate_limit: str = "10/minute"
    trusted_proxy_hops: int = 1
    # Proxys de confiance (IP/CIDR) dont on accepte X-Forwarded-For : le WAF seul (IP fixe sur `app`,
    # cf. compose). Vide = aucune confiance, l'IP cliente est celle du pair TCP (anti-usurpation).
    trusted_proxies: tuple[str, ...] = ()
    run_migrations: bool = True
    enable_docs: bool = False
    register_initial_balance_cents: int = 0
    # Plafond mensuel (#46) d'un compte ouvert par /register : un client, pas un compte de service.
    register_monthly_limit_cents: int = 80_000
    log_level: str = "INFO"
    # Back-office à étapes (consigne additionnelle 1)
    face_id_url: str = "http://face-id:8006"
    face_internal_token: str = ""  # token envoyé à face-id (défense en profondeur)
    face_timeout_seconds: float = 2.0  # borne l'appel face-id (protège le threadpool de /login)
    backoffice_max_attempts: int = 2
    backoffice_lockout_seconds: int = 300
    backoffice_challenge_ttl: int = 60
    backoffice_failure_window: int = 900
    backoffice_rate_limit: str = "30/minute"
    backoffice_face_required: bool = True
    # IP EXACTES exemptées du rate-limit de /login : la vérification automatique (verify_tx de la
    # remédiation, IP interne fixe). Sans elle, tighten_rate_limit faisait échouer la preuve de reprise
    # (constaté le 21/10). Jamais de plage : les clients externes arrivent par une passerelle Docker.
    rate_limit_exempt_ips: tuple[str, ...] = ()
    # Retour automatique à la limite de base après un durcissement (s) ; 0 = jamais.
    rate_limit_restore_seconds: int = 300
    backoffice_reject_cooldown: int = 30  # refroidissement après visage refusé (s)
    backoffice_fail_cooldown: int = 3  # refroidissement après mot de passe refusé (s)
    # LED MQTT (contrat §5.3) : MQTT_HOST vide => LogLedNotifier (aucun broker requis)
    mqtt_host: str = ""
    mqtt_port: int = 1883
    mqtt_username: str = "auth"
    mqtt_password: str = ""
    # Bootstrap du premier administrateur : secret optionnel, vide => jamais requis (refusé).
    backoffice_bootstrap_token: str = ""

    def __post_init__(self) -> None:
        if len(self.jwt_secret) < MIN_SECRET_LENGTH:
            raise RuntimeError(f"JWT_SECRET trop court (min {MIN_SECRET_LENGTH} caractères)")
        if len(self.internal_token) < 16:
            raise RuntimeError("INTERNAL_TOKEN trop court (min 16 caractères)")
        if not _RATE_RE.match(self.login_rate_limit):
            raise RuntimeError("LOGIN_RATE_LIMIT invalide (format attendu : '10/minute')")
        if not _RATE_RE.match(self.register_rate_limit):
            raise RuntimeError("REGISTER_RATE_LIMIT invalide (format attendu : '10/minute')")
        if not _RATE_RE.match(self.backoffice_rate_limit):
            raise RuntimeError("BACKOFFICE_RATE_LIMIT invalide (format attendu : '30/minute')")
        try:
            parse_trusted_proxies(self.trusted_proxies)
        except ValueError as exc:
            raise RuntimeError(f"TRUSTED_PROXIES invalide : {exc}") from exc

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            jwt_secret=read_secret("JWT_SECRET"),
            internal_token=read_secret("INTERNAL_TOKEN"),
            login_rate_limit=os.environ.get("LOGIN_RATE_LIMIT", "10/minute"),
            register_rate_limit=os.environ.get("REGISTER_RATE_LIMIT", "10/minute"),
            trusted_proxy_hops=int(os.environ.get("TRUSTED_PROXY_HOPS", "1")),
            trusted_proxies=tuple(
                p.strip() for p in os.environ.get("TRUSTED_PROXIES", "").split(",") if p.strip()
            ),
            run_migrations=_bool("RUN_MIGRATIONS", True),
            enable_docs=_bool("ENABLE_DOCS", False),
            register_initial_balance_cents=int(
                os.environ.get("REGISTER_INITIAL_BALANCE_CENTS", "0")
            ),
            register_monthly_limit_cents=int(
                os.environ.get("REGISTER_MONTHLY_LIMIT_CENTS", "80000")
            ),
            log_level=os.environ.get("LOG_LEVEL", "INFO").upper(),
            face_id_url=os.environ.get("FACE_ID_URL", "http://face-id:8006"),
            face_internal_token=_read_face_token(),
            face_timeout_seconds=float(os.environ.get("BACKOFFICE_FACE_TIMEOUT", "2.0")),
            backoffice_max_attempts=int(os.environ.get("BACKOFFICE_MAX_ATTEMPTS", "2")),
            backoffice_lockout_seconds=int(os.environ.get("BACKOFFICE_LOCKOUT_SECONDS", "300")),
            backoffice_challenge_ttl=int(os.environ.get("BACKOFFICE_CHALLENGE_TTL", "60")),
            backoffice_failure_window=int(os.environ.get("BACKOFFICE_FAILURE_WINDOW", "900")),
            backoffice_rate_limit=os.environ.get("BACKOFFICE_RATE_LIMIT", "30/minute"),
            backoffice_face_required=_bool("BACKOFFICE_FACE_REQUIRED", True),
            rate_limit_exempt_ips=tuple(
                ip.strip() for ip in os.environ.get("RATE_LIMIT_EXEMPT_IPS", "").split(",") if ip.strip()
            ),
            rate_limit_restore_seconds=int(os.environ.get("RATE_LIMIT_RESTORE_SECONDS", "300")),
            backoffice_reject_cooldown=int(os.environ.get("BACKOFFICE_REJECT_COOLDOWN", "30")),
            backoffice_fail_cooldown=int(os.environ.get("BACKOFFICE_FAIL_COOLDOWN", "3")),
            mqtt_host=os.environ.get("MQTT_HOST", ""),
            mqtt_port=int(os.environ.get("MQTT_PORT", "1883")),
            mqtt_username=os.environ.get("MQTT_USERNAME", "auth"),
            mqtt_password=read_secret("MQTT_AUTH_PASSWORD", required=False) or "",
            backoffice_bootstrap_token=read_secret("BACKOFFICE_BOOTSTRAP_TOKEN", required=False)
            or "",
        )
