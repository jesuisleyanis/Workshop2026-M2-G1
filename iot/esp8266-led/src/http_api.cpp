#include "http_api.h"

#include "secrets.h"

HttpApi::HttpApi(LedDevice& led) : led_(led) {}

void HttpApi::begin() {
    server_.on("/api/v1/led/green/blink", HTTP_POST, [this]() {
        command(resilience::LedState::Recognized);
    });
    server_.on("/api/v1/led/green/solid", HTTP_POST, [this]() {
        command(resilience::LedState::AuthOk);
    });
    server_.on("/api/v1/led/red/blink", HTTP_POST, [this]() {
        command(resilience::LedState::AuthFail);
    });
    server_.begin();
}

void HttpApi::tick(bool wifiConnected) {
    if (wifiConnected) server_.handleClient();
}

void HttpApi::command(resilience::LedState state) {
    if (!server_.authenticate(LED_HTTP_USERNAME, LED_HTTP_PASSWORD)) {
        server_.requestAuthentication();
        return;
    }

    led_.setState(state, millis());
    server_.sendHeader("Cache-Control", "no-store");
    server_.send(204, "text/plain", "");
}
