"""Configuration du moteur de remédiation (variables d'environnement uniquement).

Aucun secret n'a de valeur par défaut. Les tokens peuvent être fournis en clair via
l'environnement (dev) ou, de préférence, via un fichier (`*_FILE`) alimenté par SOPS/age
déchiffré au démarrage (secret monté en lecture seule, jamais dans l'image).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

HERE = Path(__file__).resolve().parent
MIN_TOKEN_LENGTH = 16


def _bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _csv(value: str | None, default: tuple[str, ...]) -> tuple[str, ...]:
    if value is None:
        return default
    return tuple(v.strip() for v in value.split(",") if v.strip())


def _secret(env: Mapping[str, str], name: str) -> str | None:
    """Lit un secret depuis NAME_FILE (prioritaire) ou NAME."""
    file_path = env.get(f"{name}_FILE")
    if file_path:
        try:
            return Path(file_path).read_text(encoding="utf-8").strip() or None
        except OSError:
            return None
    value = env.get(name)
    return value.strip() if value and value.strip() else None


@dataclass(frozen=True)
class Settings:
    # --- Authentification de l'API (POST /events, /stream, /incidents) ---
    token: str | None = None  # REMEDIATION_TOKEN
    # --- Appels sortants ---
    internal_token: str | None = None  # INTERNAL_TOKEN (API interne du service auth)
    docker_proxy_url: str = "http://docker-socket-proxy:2375"
    docker_allow_recreate: bool = False  # recreate_service : profil proxy élargi requis
    restartable_services: tuple[str, ...] = ("payment-api", "auth", "front")
    auth_url: str = "http://auth:8002"
    loki_url: str = "http://loki:3100"
    notify_webhook_url: str | None = None
    # --- Table, journal, vérification ---
    decision_table_path: Path = HERE / "decision_table.yml"
    db_path: str = "incidents.db"
    verify_tx_path: str = "scripts/verify_tx"
    verify_timeout_s: float = 30.0
    verify_retries: int = 5  # la plateforme met du temps à redevenir saine
    verify_interval_s: float = 3.0
    action_timeout_s: float = 300.0
    # --- Ansible (restauration pg_restore) ---
    ansible_private_data_dir: str = "/opt/ansible"
    # --- Liste de blocage du WAF : dossier partagé avec le WAF (monté en écriture ici, en lecture
    # seule là-bas) ; le WAF détecte le changement et se recharge (98-blocklist-watch.sh).
    blocklist_path: str = "/var/lib/waf-blocklist/blocked_ips.conf"
    blocklist_max_entries: int = 1000
    # --- Garde-fous ---
    dry_run: bool = False  # REMEDIATION_DRY_RUN : peut seulement FORCER le dry-run
    never_block_ips: tuple[str, ...] = ("127.0.0.1", "::1", "192.168.137.1")
    # --- SSE ---
    sse_keepalive_s: float = 15.0
    service_name: str = field(default="remediation")

    @property
    def token_configured(self) -> bool:
        return bool(self.token) and len(self.token or "") >= MIN_TOKEN_LENGTH

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Settings":
        e = os.environ if env is None else env
        d = cls()
        return cls(
            token=_secret(e, "REMEDIATION_TOKEN"),
            internal_token=_secret(e, "INTERNAL_TOKEN"),
            docker_proxy_url=e.get("DOCKER_PROXY_URL", d.docker_proxy_url).rstrip("/"),
            docker_allow_recreate=_bool(e.get("DOCKER_PROXY_ALLOW_RECREATE")),
            restartable_services=_csv(e.get("RESTARTABLE_SERVICES"), d.restartable_services),
            auth_url=e.get("AUTH_URL", d.auth_url).rstrip("/"),
            loki_url=e.get("LOKI_URL", d.loki_url).rstrip("/"),
            notify_webhook_url=e.get("NOTIFY_WEBHOOK_URL") or None,
            decision_table_path=Path(e.get("DECISION_TABLE", str(d.decision_table_path))),
            db_path=e.get("INCIDENTS_DB", d.db_path),
            verify_tx_path=e.get("VERIFY_TX_PATH", d.verify_tx_path),
            verify_timeout_s=float(e.get("VERIFY_TIMEOUT_S", d.verify_timeout_s)),
            verify_retries=int(e.get("VERIFY_RETRIES", d.verify_retries)),
            verify_interval_s=float(e.get("VERIFY_INTERVAL_S", d.verify_interval_s)),
            action_timeout_s=float(e.get("ACTION_TIMEOUT_S", d.action_timeout_s)),
            ansible_private_data_dir=e.get("ANSIBLE_PRIVATE_DATA_DIR", d.ansible_private_data_dir),
            dry_run=_bool(e.get("REMEDIATION_DRY_RUN")),
            blocklist_path=e.get("BLOCKLIST_PATH", d.blocklist_path),
            blocklist_max_entries=int(e.get("BLOCKLIST_MAX_ENTRIES", d.blocklist_max_entries)),
            never_block_ips=_csv(e.get("NEVER_BLOCK_IPS"), d.never_block_ips),
            sse_keepalive_s=float(e.get("SSE_KEEPALIVE_S", d.sse_keepalive_s)),
        )
