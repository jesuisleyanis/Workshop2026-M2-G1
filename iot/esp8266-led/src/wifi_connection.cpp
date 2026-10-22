#include "wifi_connection.h"

#include <ESP8266WiFi.h>

#include "secrets.h"

namespace {

constexpr uint32_t kRetryMs = 5000;

}  // namespace

void WifiConnection::begin() {
    WiFi.mode(WIFI_STA);
    WiFi.persistent(false);
    tryConnect(millis());
}

void WifiConnection::tick(uint32_t now) {
    if (connected()) {
        if (!wasConnected_) {
            Serial.print("WiFi connected, IP: ");
            Serial.println(WiFi.localIP());
        }
        wasConnected_ = true;
        return;
    }

    if (wasConnected_) Serial.println("WiFi disconnected");
    wasConnected_ = false;
    if (now - lastAttemptMs_ >= kRetryMs) tryConnect(now);
}

bool WifiConnection::connected() const {
    return WiFi.status() == WL_CONNECTED;
}

void WifiConnection::tryConnect(uint32_t now) {
    lastAttemptMs_ = now;
    Serial.println("WiFi connecting...");
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
}
