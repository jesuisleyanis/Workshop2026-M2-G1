"""Tests du notifieur LED MQTT (contrat §5.3) : aucun réseau, client paho remplacé par un faux."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from authkit import JWT_SECRET
from fastapi.testclient import TestClient
from resilience_common.events import RESERVED_EVENTS
from resilience_common.logging import get_logger
from resilience_common.metrics import led_publish_total
from resilience_db import Base, make_engine

from auth_service.backoffice import LogLedNotifier
from auth_service.config import SERVICE_NAME, Settings
from auth_service.led_mqtt import LED_CMD_TOPIC, LED_STATUS_TOPIC, MqttLedNotifier
from auth_service.main import create_app


class FakeMqttClient:
    """Double minimal du client paho 2.x (mêmes méthodes/attributs utilisés par le notifieur)."""

    def __init__(self) -> None:
        self.connected = True
        self.raise_on_publish: Exception | None = None
        self.publish_rc = 0
        self.published: list[dict] = []
        self.subscriptions: list[tuple[str, int]] = []
        self.credentials: tuple[str, str] | None = None
        self.reconnect_delay: tuple[int, int] | None = None
        self.connect_async_args: tuple | None = None
        self.loop_started = False
        self.loop_stopped = False
        self.disconnected = False
        self.on_connect = None
        self.on_message = None

    def username_pw_set(self, username, password=None):
        self.credentials = (username, password)

    def reconnect_delay_set(self, min_delay=1, max_delay=120):
        self.reconnect_delay = (min_delay, max_delay)

    def connect_async(self, host, port=1883, keepalive=60):
        self.connect_async_args = (host, port)

    def loop_start(self):
        self.loop_started = True

    def loop_stop(self):
        self.loop_stopped = True

    def disconnect(self):
        self.disconnected = True

    def subscribe(self, topic, qos=0):
        self.subscriptions.append((topic, qos))

    def is_connected(self):
        return self.connected

    def publish(self, topic, payload=None, qos=0, retain=False):
        if self.raise_on_publish is not None:
            raise self.raise_on_publish
        self.published.append({"topic": topic, "payload": payload, "qos": qos, "retain": retain})
        return SimpleNamespace(rc=self.publish_rc)

    # -- helpers de test : simulent les callbacks de la boucle réseau paho
    def fire_connect(self):
        self.on_connect(self, None, {}, 0, None)

    def fire_message(self, payload, topic: str = LED_STATUS_TOPIC):
        data = payload if isinstance(payload, bytes) else payload.encode()
        self.on_message(self, None, SimpleNamespace(topic=topic, payload=data))


FIXED = datetime(2026, 10, 20, 8, 30, 15, tzinfo=UTC)
CHALLENGE = "11111111-1111-4111-8111-111111111111"


@pytest.fixture
def fake():
    return FakeMqttClient()


@pytest.fixture
def log():
    return get_logger(SERVICE_NAME)


@pytest.fixture
def notifier(fake, log):
    return MqttLedNotifier(
        "mqtt-host", 1883, "auth", "s3cret", log, client_factory=lambda: fake, clock=lambda: FIXED
    )


def _count(state: str, result: str) -> float:
    return led_publish_total.labels(state, result)._value.get()


def test_event_names_are_reserved():
    assert {"led_state_published", "led_publish_failed"} <= RESERVED_EVENTS


def test_topics_follow_contract():
    assert LED_CMD_TOPIC == "resilience/led/cmd"
    assert LED_STATUS_TOPIC == "resilience/led/status"


def test_start_configures_client_and_subscribes_on_each_connect(notifier, fake):
    notifier.start()
    assert fake.credentials == ("auth", "s3cret")
    assert fake.reconnect_delay == (1, 30)
    assert fake.connect_async_args == ("mqtt-host", 1883)
    assert fake.loop_started
    assert fake.subscriptions == []  # l'abonnement se fait au on_connect (survit aux reconnexions)
    fake.fire_connect()
    fake.fire_connect()
    assert fake.subscriptions == [(LED_STATUS_TOPIC, 1), (LED_STATUS_TOPIC, 1)]


def test_start_without_credentials_skips_username_pw_set(fake, log):
    n = MqttLedNotifier("h", 1883, "", "", log, client_factory=lambda: fake)
    n.start()
    assert fake.credentials is None


def test_stop_stops_loop_and_disconnects(notifier, fake):
    notifier.start()
    notifier.stop()
    assert fake.disconnected and fake.loop_stopped


def test_publish_payload_topic_qos(notifier, fake):
    before = _count("auth_ok", "ok")
    notifier.publish("auth_ok", CHALLENGE)
    (msg,) = fake.published
    assert msg["topic"] == LED_CMD_TOPIC
    assert msg["qos"] == 1
    assert msg["retain"] is False
    assert json.loads(msg["payload"]) == {
        "state": "auth_ok",
        "ts": "2026-10-20T08:30:15Z",
        "challenge_id": CHALLENGE,
    }
    assert _count("auth_ok", "ok") == before + 1


def test_publish_null_challenge_id(notifier, fake):
    notifier.publish("idle", None)
    assert json.loads(fake.published[0]["payload"])["challenge_id"] is None


def test_ts_is_iso8601_utc_with_z_by_default(fake, log):
    n = MqttLedNotifier("h", 1883, "", "", log, client_factory=lambda: fake)
    n.publish("idle", None)
    ts = json.loads(fake.published[0]["payload"])["ts"]
    assert ts.endswith("Z")
    assert datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ")


def test_publish_logs_state_published(notifier, log_lines):
    notifier.publish("recognized", None)
    assert len(log_lines("led_state_published")) == 1


def test_publish_swallows_client_exception(notifier, fake, log_lines):
    fake.raise_on_publish = OSError("broker down")
    before = _count("auth_fail", "error")
    notifier.publish("auth_fail", None)  # ne doit pas lever
    assert _count("auth_fail", "error") == before + 1
    assert len(log_lines("led_publish_failed")) == 1


def test_publish_when_disconnected_is_error(notifier, fake, log_lines):
    fake.connected = False
    before = _count("idle", "error")
    notifier.publish("idle", None)
    assert fake.published == []
    assert _count("idle", "error") == before + 1
    assert len(log_lines("led_publish_failed")) == 1


def test_publish_nonzero_rc_is_error(notifier, fake, log_lines):
    fake.publish_rc = 4
    before = _count("not_recognized", "error")
    notifier.publish("not_recognized", None)
    assert _count("not_recognized", "error") == before + 1
    assert len(log_lines("led_publish_failed")) == 1


def test_online_none_until_status_received(notifier):
    assert notifier.online is None


def test_status_messages_update_online(notifier, fake):
    notifier.start()
    fake.fire_message('{"online": true}')
    assert notifier.online is True
    fake.fire_message('{"online": false}')
    assert notifier.online is False


@pytest.mark.parametrize(
    "payload", [b"not json", b"\xff\xfe", b"[1]", b'{"online": "yes"}', b'{"other": 1}', b"null"]
)
def test_invalid_status_is_ignored(notifier, fake, payload):
    notifier.start()
    fake.fire_message(b'{"online": true}')
    fake.fire_message(payload)
    assert notifier.online is True


def test_status_on_other_topic_ignored(notifier, fake):
    notifier.start()
    fake.fire_message('{"online": true}', topic="other/topic")
    assert notifier.online is None


# --------------------------------------------------------------------------- intégration app


class _OnlineLed:
    def __init__(self, online):
        self.online = online
        self.started = 0
        self.stopped = 0

    def publish(self, state, challenge_id):
        pass

    def start(self):
        self.started += 1

    def stop(self):
        self.stopped += 1


def _app(led=None, **extra):
    engine = make_engine("sqlite://")
    Base.metadata.create_all(engine)
    settings = Settings(
        jwt_secret=JWT_SECRET,
        internal_token="internal-token-for-tests",
        face_internal_token="face-internal-token-tests-0123",
        run_migrations=False,
        **extra,
    )
    return create_app(settings, engine, led_notifier=led)


@pytest.mark.parametrize("value", [True, False, None])
def test_device_route_reports_led_online(value):
    with TestClient(_app(_OnlineLed(value))) as client:
        r = client.get("/api/v1/auth/device")
    assert r.status_code == 200
    assert r.json() == {"led_online": value}


def test_device_route_null_for_log_notifier():
    with TestClient(_app()) as client:
        assert client.get("/api/v1/auth/device").json() == {"led_online": None}


def test_lifespan_starts_and_stops_notifier():
    led = _OnlineLed(None)
    with TestClient(_app(led)):
        assert led.started == 1
        assert led.stopped == 0
    assert led.stopped == 1


def test_no_mqtt_host_uses_log_notifier():
    app = _app()
    assert isinstance(app.state.led, LogLedNotifier)


def test_mqtt_host_builds_mqtt_notifier():
    app = _app(mqtt_host="mosquitto", mqtt_port=1884, mqtt_username="auth", mqtt_password="pw")
    assert isinstance(app.state.led, MqttLedNotifier)  # non démarré : aucun réseau sans lifespan


def test_settings_from_env_mqtt(monkeypatch, tmp_path):
    secret = tmp_path / "pw"
    secret.write_text("filepw\n")
    monkeypatch.setenv("JWT_SECRET", JWT_SECRET)
    monkeypatch.setenv("INTERNAL_TOKEN", "internal-token-for-tests")
    monkeypatch.setenv("MQTT_HOST", "mosquitto")
    monkeypatch.setenv("MQTT_PORT", "1884")
    monkeypatch.setenv("MQTT_AUTH_PASSWORD_FILE", str(secret))
    monkeypatch.delenv("MQTT_AUTH_PASSWORD", raising=False)
    s = Settings.from_env()
    assert (s.mqtt_host, s.mqtt_port, s.mqtt_username, s.mqtt_password) == (
        "mosquitto",
        1884,
        "auth",
        "filepw",
    )


def test_settings_from_env_defaults_without_mqtt(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", JWT_SECRET)
    monkeypatch.setenv("INTERNAL_TOKEN", "internal-token-for-tests")
    for var in (
        "MQTT_HOST",
        "MQTT_PORT",
        "MQTT_USERNAME",
        "MQTT_AUTH_PASSWORD",
        "MQTT_AUTH_PASSWORD_FILE",
    ):
        monkeypatch.delenv(var, raising=False)
    s = Settings.from_env()
    assert (s.mqtt_host, s.mqtt_port, s.mqtt_username, s.mqtt_password) == ("", 1883, "auth", "")
