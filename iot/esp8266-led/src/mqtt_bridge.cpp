#include "mqtt_bridge.h"

#include <ArduinoJson.h>
#include <cstring>

#include "secrets.h"

namespace {

constexpr char kCommandTopic[] = "resilience/led/cmd";
constexpr char kStatusTopic[] = "resilience/led/status";
constexpr uint32_t kRetryMs = 5000;
constexpr uint32_t kHeartbeatMs = 15000;

}  // namespace

MqttBridge::MqttBridge(LedDevice& led) : led_(led) {}

void MqttBridge::begin() {
    mqtt_.setServer(MQTT_HOST, MQTT_PORT);
    mqtt_.setSocketTimeout(1);
    mqtt_.setCallback([this](char* topic, uint8_t* payload, unsigned int length) {
        onMessage(topic, payload, length);
    });
}

void MqttBridge::tick(uint32_t now, bool wifiConnected) {
    if (!wifiConnected) return;

    if (!mqtt_.connected()) {
        if (!attempted_ || now - lastAttemptMs_ >= kRetryMs) connect(now);
        if (!mqtt_.connected()) return;
    }

    mqtt_.loop();
    if (now - lastHeartbeatMs_ >= kHeartbeatMs) {
        lastHeartbeatMs_ = now;
        mqtt_.publish(kStatusTopic, "{\"online\":true}", true);
    }
}

void MqttBridge::connect(uint32_t now) {
    lastAttemptMs_ = now;
    attempted_ = true;
    if (mqtt_.connect(MQTT_CLIENT_ID, MQTT_USERNAME, MQTT_PASSWORD, kStatusTopic, 0, true,
                      "{\"online\":false}")) {
        mqtt_.publish(kStatusTopic, "{\"online\":true}", true);
        mqtt_.subscribe(kCommandTopic, 1);
        lastHeartbeatMs_ = now;
    }
}

void MqttBridge::onMessage(char* topic, uint8_t* payload, unsigned int length) {
    if (std::strcmp(topic, kCommandTopic) != 0) return;

    JsonDocument doc;
    if (deserializeJson(doc, payload, length)) return;
    const char* value = doc["state"] | static_cast<const char*>(nullptr);
    resilience::LedState state;
    if (resilience::led_state_from_string(value, state)) led_.setState(state, millis());
}
