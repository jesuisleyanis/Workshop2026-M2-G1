"""Contrat infra de l'intégration face-id / back-office / MQTT (vérifiable sans Docker).

Lit le Compose, la config Mosquitto, l'ACL, le Prometheus et le fichier d'exemple SOPS.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = yaml.safe_load((ROOT / "infra" / "compose" / "docker-compose.yml").read_text(encoding="utf-8"))
SERVICES = COMPOSE["services"]
MOSQ = ROOT / "infra" / "mosquitto"
NEW_SERVICES = ("face-id", "backoffice", "mosquitto")


def _tmpfs_paths(svc: dict) -> list[str]:
    return [t.split(":")[0] for t in (svc.get("tmpfs") or [])]


def test_new_services_are_hardened() -> None:
    for name in NEW_SERVICES:
        svc = SERVICES[name]
        assert svc.get("cap_drop") == ["ALL"], name
        assert "no-new-privileges:true" in svc.get("security_opt", []), name
        assert svc.get("read_only") is True, name
        assert svc.get("healthcheck"), name
        assert svc.get("mem_limit"), name


def test_only_waf_and_mosquitto_publish_ports() -> None:
    assert {n for n, s in SERVICES.items() if "ports" in s} == {"waf", "mosquitto"}


def test_host_listener_9443_is_published_on_loopback_only() -> None:
    ports = SERVICES["waf"]["ports"]
    assert "127.0.0.1:9443:9443" in ports
    for p in ports:
        if p.endswith(":9443"):
            assert p.startswith("127.0.0.1:"), "9443 ne doit jamais être publié hors loopback"
    assert "backoffice" in SERVICES["waf"]["depends_on"]


def test_mosquitto_not_published_on_all_interfaces() -> None:
    mosq = SERVICES["mosquitto"]
    assert mosq["image"] == "eclipse-mosquitto:2.0.20"
    assert mosq["ports"] == ["${MQTT_BIND:-192.168.137.1}:1883:1883"]
    for p in mosq["ports"]:
        assert not p.startswith(("0.0.0.0:", "1883:", ":")), "MQTT jamais sur 0.0.0.0"
    assert mosq["networks"] == ["app"]
    assert mosq["user"] == "1883:1883"


def test_mosquitto_passwd_lives_in_tmpfs_run_dir_and_config_is_read_only() -> None:
    mosq = SERVICES["mosquitto"]
    run = [t for t in mosq["tmpfs"] if t.startswith("/mosquitto/run")]
    assert run and "uid=1883" in run[0] and "gid=1883" in run[0] and "mode=0700" in run[0]
    for v in mosq["volumes"]:
        assert v.endswith(":ro"), f"volume mosquitto non read-only : {v}"
    assert any("docker-entrypoint.sh" in v for v in mosq["volumes"])
    assert "docker-entrypoint.sh" in " ".join(mosq["entrypoint"])
    env = mosq["environment"]
    assert env["MQTT_AUTH_PASSWORD"] == "${MQTT_AUTH_PASSWORD}"
    assert env["MQTT_LED_PASSWORD"] == "${MQTT_LED_PASSWORD}"
    hc = " ".join(mosq["healthcheck"]["test"])
    assert "mosquitto_sub" in hc and "$$SYS/broker/uptime" in hc and "-u auth" in hc


def test_mosquitto_conf_and_entrypoint_agree_on_passwd_path() -> None:
    conf = (MOSQ / "mosquitto.conf").read_text(encoding="utf-8")
    assert re.search(r"^password_file /mosquitto/run/passwd\s*$", conf, re.M)
    sh = (MOSQ / "docker-entrypoint.sh").read_text(encoding="utf-8")
    assert "/mosquitto/run/passwd" in sh
    assert re.search(r"mosquitto_passwd -b -c \S+ auth ", sh)
    assert re.search(r"mosquitto_passwd -b \S+ led ", sh)
    assert "MQTT_AUTH_PASSWORD" in sh and "MQTT_LED_PASSWORD" in sh
    assert "exec mosquitto -c /mosquitto/config/mosquitto.conf" in sh
    assert sh.index("mosquitto_passwd") < sh.index("exec mosquitto")
    # Échec franc si un mot de passe est vide (pas de broker sans creds).
    assert re.search(r'-z\s+"\$\{MQTT_AUTH_PASSWORD', sh) and re.search(r'-z\s+"\$\{MQTT_LED_PASSWORD', sh)
    assert "set -e" in sh


def test_acl_auth_reads_led_status_and_least_privilege_kept() -> None:
    acl = (MOSQ / "aclfile").read_text(encoding="utf-8")
    blocks: dict[str, list[str]] = {}
    cur = None
    for line in acl.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("user "):
            cur = line.split()[1]
            blocks[cur] = []
        else:
            blocks[cur].append(line)
    assert "topic write resilience/led/cmd" in blocks["auth"]
    assert "topic read resilience/led/status" in blocks["auth"]
    assert "topic read resilience/led/cmd" in blocks["led"]
    assert "topic write resilience/led/status" in blocks["led"]


def test_face_id_service() -> None:
    f = SERVICES["face-id"]
    assert f["build"] == {"context": "../..", "dockerfile": "services/face-id/Dockerfile"}
    assert f["networks"] == ["app", "data"]
    env = f["environment"]
    for k in ("POSTGRES_HOST", "POSTGRES_DB", "POSTGRES_USER", "POSTGRES_PASSWORD",
              "FACE_INTERNAL_TOKEN", "FACE_DATA_KEY"):
        assert k in env, k
    assert env["FACE_INTERNAL_TOKEN"] == "${FACE_INTERNAL_TOKEN}"
    assert env["FACE_DATA_KEY"] == "${FACE_DATA_KEY}"
    assert env["RECOGNIZER_BACKEND"] == "team"
    assert "/tmp" in _tmpfs_paths(f)
    assert f["mem_limit"] == "1g" and float(f["cpus"]) == 1.5
    assert "8006/health" in " ".join(f["healthcheck"]["test"])
    assert "postgres" in f["depends_on"]


def test_backoffice_service() -> None:
    b = SERVICES["backoffice"]
    assert b["build"] == {"context": "../../services/backoffice"}
    assert b["networks"] == ["app"]
    assert "/tmp" in _tmpfs_paths(b)
    assert b["mem_limit"] == "128m"
    assert "8080/healthz" in " ".join(b["healthcheck"]["test"])


def test_auth_wired_to_face_id_and_mqtt() -> None:
    a = SERVICES["auth"]
    env = a["environment"]
    assert env["FACE_ID_URL"] == "http://face-id:8006"
    assert env["FACE_INTERNAL_TOKEN"] == "${FACE_INTERNAL_TOKEN}"
    assert env["MQTT_HOST"] == "mosquitto"
    assert env["MQTT_AUTH_PASSWORD"] == "${MQTT_AUTH_PASSWORD}"
    assert env["BACKOFFICE_BOOTSTRAP_TOKEN"] == "${BACKOFFICE_BOOTSTRAP_TOKEN}"
    assert set(a["depends_on"]) >= {"postgres", "face-id", "mosquitto"}


def test_prometheus_scrapes_face_id() -> None:
    jobs = yaml.safe_load((ROOT / "infra" / "prometheus" / "prometheus.yml").read_text(encoding="utf-8"))["scrape_configs"]
    job = next(j for j in jobs if j["job_name"] == "face-id")
    assert job["static_configs"][0]["targets"] == ["face-id:8006"]


def test_sops_example_has_new_secrets_with_fake_values() -> None:
    env = dict(
        line.split("=", 1)
        for line in (ROOT / "security" / "sops" / "secrets.example.env").read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#") and "=" in line
    )
    for k in ("FACE_INTERNAL_TOKEN", "FACE_DATA_KEY", "MQTT_AUTH_PASSWORD", "MQTT_LED_PASSWORD",
              "BACKOFFICE_BOOTSTRAP_TOKEN", "MQTT_BIND"):
        assert k in env, k
    for k in ("FACE_INTERNAL_TOKEN", "MQTT_AUTH_PASSWORD", "MQTT_LED_PASSWORD", "BACKOFFICE_BOOTSTRAP_TOKEN"):
        assert env[k].startswith("change-me"), k
    assert "change-me" in env["FACE_DATA_KEY"]
    assert env["MQTT_BIND"] == "192.168.137.1"
