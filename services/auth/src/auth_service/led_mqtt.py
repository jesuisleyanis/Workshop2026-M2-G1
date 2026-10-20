"""Publication de l'état de la LED bicolore vers le broker MQTT (contrat §5.3).

`auth` ne publie que des états **sémantiques** (`idle`, `recognized`, `auth_ok`, `auth_fail`,
`not_recognized`) : le firmware ESP8266 (iot/esp8266-led) rend les motifs et les durées.
Le même objet écoute `resilience/led/status` (heartbeats retained + LWT `{"online": false}`)
pour exposer l'état du module à `GET /api/v1/auth/device`.

**Fail-open** : `publish` ne bloque jamais la requête (le QoS 1 est mis en file par la boucle
réseau de paho, qui tourne dans son propre thread) et ne propage jamais d'exception : la LED
est un témoin, pas un facteur d'authentification.

État du module : `online` repasse à `None` (inconnu) dès que la connexion au broker est perdue
ou refusée — un `true` retenu d'avant la coupure ne doit pas être affiché comme courant. Un refus
du broker (`on_connect` en échec : identifiants, ACL...) est journalisé `led_publish_failed`
avec le seul code de raison, jamais d'identifiant secret.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime

import paho.mqtt.client as mqtt
from resilience_common.metrics import led_publish_total

from auth_service.observability import log_event

LED_CMD_TOPIC = "resilience/led/cmd"
LED_STATUS_TOPIC = "resilience/led/status"


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _is_failure(reason_code) -> bool:
    """paho 2.x passe un `ReasonCode` (attribut `is_failure`) ; les doubles de test, un int."""
    failure = getattr(reason_code, "is_failure", None)
    if isinstance(failure, bool):
        return failure
    return reason_code != 0


def _default_client_factory() -> mqtt.Client:
    return mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2, client_id="resilience-auth"
    )


class MqttLedNotifier:
    """Notifieur LED MQTT (implémente `LedNotifier`, plus `start`/`stop`/`online`)."""

    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        log: logging.Logger,
        *,
        client_factory: Callable[[], mqtt.Client] = _default_client_factory,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._log = log
        self._clock = clock
        self._client = client_factory()
        self._online: bool | None = None

    # ------------------------------------------------------------------ cycle de vie
    def start(self) -> None:
        """Démarre la boucle réseau en arrière-plan (connexion asynchrone, reconnexion auto)."""
        client = self._client
        if self._username:
            client.username_pw_set(self._username, self._password)
        client.reconnect_delay_set(1, 30)
        client.on_connect = self._on_connect
        client.on_disconnect = self._on_disconnect
        client.on_message = self._on_message
        client.connect_async(self._host, self._port)
        client.loop_start()

    def stop(self) -> None:
        try:
            self._client.disconnect()
            self._client.loop_stop()
        except Exception as exc:  # noqa: BLE001 - l'arrêt ne doit jamais échouer
            log_event(
                self._log,
                logging.WARNING,
                "led_publish_failed",
                f"LED MQTT stop failed: {type(exc).__name__}",
            )

    # ------------------------------------------------------------------ callbacks paho
    def _on_connect(self, client, _userdata, _flags, reason_code, _properties=None) -> None:
        if _is_failure(reason_code):
            # Broker joint mais connexion refusée (mot de passe, ACL...) : paho réessaiera.
            self._online = None
            log_event(
                self._log,
                logging.WARNING,
                "led_publish_failed",
                f"MQTT connection to {self._host}:{self._port} refused (reason: {reason_code})",
            )
            return
        # Abonnement à chaque (re)connexion : la session n'est pas garantie persistante.
        client.subscribe(LED_STATUS_TOPIC, qos=1)

    def _on_disconnect(
        self, _client, _userdata, _flags=None, _reason_code=None, _properties=None
    ) -> None:
        # Plus de lien avec le broker : l'état du module redevient inconnu jusqu'au prochain
        # message retenu (reçu à la réabonnement après reconnexion).
        self._online = None

    def _on_message(self, _client, _userdata, message) -> None:
        if message.topic != LED_STATUS_TOPIC:
            return
        try:
            data = json.loads(bytes(message.payload).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return  # JSON invalide : ignoré
        if isinstance(data, dict) and isinstance(data.get("online"), bool):
            self._online = data["online"]

    @property
    def online(self) -> bool | None:
        """Dernier `{"online": bool}` reçu du module ; None si jamais reçu."""
        return self._online

    # ------------------------------------------------------------------ publication
    def publish(self, state: str, challenge_id: str | None) -> None:
        try:
            if not self._client.is_connected():
                raise ConnectionError("broker MQTT non connecté")
            payload = json.dumps(
                {
                    "state": state,
                    "ts": self._clock().astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "challenge_id": challenge_id,
                }
            )
            info = self._client.publish(LED_CMD_TOPIC, payload, qos=1, retain=False)
            if info.rc != mqtt.MQTT_ERR_SUCCESS:
                raise ConnectionError(f"publish rc={info.rc}")
        except Exception as exc:  # noqa: BLE001 - fail-open : ne jamais bloquer l'auth
            led_publish_total.labels(state, "error").inc()
            log_event(
                self._log,
                logging.WARNING,
                "led_publish_failed",
                f"LED publish failed ({state}): {type(exc).__name__}: {exc}",
            )
            return
        led_publish_total.labels(state, "ok").inc()
        log_event(self._log, logging.INFO, "led_state_published", f"LED -> {state}")
