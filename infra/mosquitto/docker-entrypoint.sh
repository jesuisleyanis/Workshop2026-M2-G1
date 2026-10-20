#!/bin/sh
# Entrypoint du broker : génère le fichier de mots de passe dans le tmpfs /mosquitto/run (uid 1883),
# à partir des secrets injectés par Compose (SOPS), puis lance mosquitto. Racine du conteneur en lecture seule.
set -eu

PASSWD_FILE=/mosquitto/run/passwd

if [ -z "${MQTT_AUTH_PASSWORD:-}" ] || [ -z "${MQTT_LED_PASSWORD:-}" ]; then
  echo "mosquitto: MQTT_AUTH_PASSWORD et MQTT_LED_PASSWORD sont requis (voir security/sops/secrets.example.env)" >&2
  exit 1
fi

mosquitto_passwd -b -c "$PASSWD_FILE" auth "$MQTT_AUTH_PASSWORD"
mosquitto_passwd -b "$PASSWD_FILE" led "$MQTT_LED_PASSWORD"
chmod 0600 "$PASSWD_FILE"

exec mosquitto -c /mosquitto/config/mosquitto.conf
