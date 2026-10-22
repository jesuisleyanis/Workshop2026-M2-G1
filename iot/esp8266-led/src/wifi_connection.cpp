#include "wifi_connection.h"

#include <ESP8266WiFi.h>

#include "secrets.h"

namespace {

constexpr uint32_t kRetryMs = 5000;
constexpr uint32_t kConnectTimeoutMs = 30000;

}  // namespace

void WifiConnection::begin() {
    WiFi.mode(WIFI_STA);
    WiFi.persistent(false);
    WiFi.setAutoReconnect(true);
    tryConnect(millis());
}

void WifiConnection::tick(uint32_t now) {
    const wl_status_t status = WiFi.status();
    if (status == WL_CONNECTED) {
        if (!wasConnected_) {
            Serial.println("SUCCESS: WiFi connected");
            Serial.print("IP address: ");
            Serial.println(WiFi.localIP());
        }
        wasConnected_ = true;
        return;
    }

    if (wasConnected_) {
        Serial.println("WiFi disconnected");
        // Let the ESP8266 reconnect on its own before starting another attempt.
        lastAttemptMs_ = now;
    }
    wasConnected_ = false;

    // WL_DISCONNECTED is also reported while association or DHCP is in progress.
    const uint32_t retryDelay = (status == WL_DISCONNECTED || status == WL_IDLE_STATUS)
                                    ? kConnectTimeoutMs
                                    : kRetryMs;
    if (now - lastAttemptMs_ >= retryDelay) tryConnect(now);
}

bool WifiConnection::connected() const {
    return WiFi.status() == WL_CONNECTED;
}

void WifiConnection::tryConnect(uint32_t now) {
    lastAttemptMs_ = now;
    Serial.println("WiFi connecting...");
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
}
