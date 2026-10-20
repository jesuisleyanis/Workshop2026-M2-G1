// Firmware ESP8266 — LED bicolore pilotée par la phase d'authentification du back-office.
// Consigne additionnelle 1. Le firmware est VOLONTAIREMENT mince : il reçoit un état sémantique
// via MQTT et délègue le motif/timing à resilience::LedController (lib/led, testée sur PC).
//
// WiFi : point d'accès de la solution (RESILIENCE-G<n>). MQTT : broker Mosquitto du PC Hôte.
// Secrets (SSID/PSK, broker, creds) : include/secrets.h (NON versionné — cf. secrets.h.example).

#include <Arduino.h>
#include <ArduinoJson.h>
#include <ESP8266WiFi.h>
#include <PubSubClient.h>

#include <led_controller.h>

#include "secrets.h"

using resilience::LedColor;
using resilience::LedController;
using resilience::LedState;

// Câblage LED bicolore (commune cathode) : une broche par couleur + résistances.
static constexpr uint8_t PIN_GREEN = D1;
static constexpr uint8_t PIN_RED = D2;

static constexpr char TOPIC_CMD[] = "resilience/led/cmd";
static constexpr char TOPIC_STATUS[] = "resilience/led/status";
static constexpr uint32_t HEARTBEAT_MS = 15000;

static WiFiClient wifiClient;
static PubSubClient mqtt(wifiClient);
static LedController led;
static uint32_t lastHeartbeat = 0;

static void applyOutput(uint32_t now) {
    const resilience::LedOutput out = led.update(now);
    digitalWrite(PIN_GREEN, (out.color == LedColor::Green && out.on) ? HIGH : LOW);
    digitalWrite(PIN_RED, (out.color == LedColor::Red && out.on) ? HIGH : LOW);
}

static void onMessage(char* topic, byte* payload, unsigned int length) {
    (void)topic;
    JsonDocument doc;
    if (deserializeJson(doc, payload, length)) return;  // JSON invalide -> ignoré (fail-safe)
    const char* state = doc["state"] | (const char*)nullptr;
    LedState parsed;
    if (resilience::led_state_from_string(state, parsed)) {
        led.setState(parsed, millis());  // état inconnu -> on ne change rien
    }
}

static void connectWifi() {
    WiFi.mode(WIFI_STA);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
    // Non bloquant au-delà d'un plafond : la LED reste gérée même sans réseau.
    for (int i = 0; i < 40 && WiFi.status() != WL_CONNECTED; ++i) {
        delay(250);
        applyOutput(millis());
    }
}

static void reconnectMqtt() {
    if (mqtt.connected()) return;
    // LWT : si l'objet tombe, le broker publie son indisponibilité (supervision côté hôte).
    if (mqtt.connect(MQTT_CLIENT_ID, MQTT_USERNAME, MQTT_PASSWORD, TOPIC_STATUS, 0, true,
                     "{\"online\":false}")) {
        mqtt.publish(TOPIC_STATUS, "{\"online\":true}", true);
        mqtt.subscribe(TOPIC_CMD, 1);
    }
}

void setup() {
    pinMode(PIN_GREEN, OUTPUT);
    pinMode(PIN_RED, OUTPUT);
    digitalWrite(PIN_GREEN, LOW);
    digitalWrite(PIN_RED, LOW);  // défaut : éteinte (contrat §5.3)
    connectWifi();
    mqtt.setServer(MQTT_HOST, MQTT_PORT);
    mqtt.setCallback(onMessage);
}

void loop() {
    if (WiFi.status() != WL_CONNECTED) connectWifi();
    reconnectMqtt();
    mqtt.loop();

    const uint32_t now = millis();
    applyOutput(now);

    if (now - lastHeartbeat >= HEARTBEAT_MS) {
        lastHeartbeat = now;
        if (mqtt.connected()) mqtt.publish(TOPIC_STATUS, "{\"online\":true}", true);
    }
}
