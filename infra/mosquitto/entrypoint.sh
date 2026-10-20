#!/bin/sh
set -eu

: "${MQTT_AUTH_PASSWORD:?MQTT_AUTH_PASSWORD manquant}"
: "${MQTT_LED_PASSWORD:?MQTT_LED_PASSWORD manquant}"

umask 077
cp /mosquitto/config/aclfile /run/mosquitto/aclfile
chmod 600 /run/mosquitto/aclfile
mosquitto_passwd -b -c /run/mosquitto/passwd auth "$MQTT_AUTH_PASSWORD"
mosquitto_passwd -b /run/mosquitto/passwd led "$MQTT_LED_PASSWORD"
unset MQTT_AUTH_PASSWORD MQTT_LED_PASSWORD

exec mosquitto -c /mosquitto/config/mosquitto.conf
