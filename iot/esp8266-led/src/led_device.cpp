#include "led_device.h"

namespace {

// LED bicolore à cathode commune : une sortie par couleur, avec résistances.
constexpr uint8_t kGreenPin = D1;
constexpr uint8_t kRedPin = D2;
constexpr uint32_t kWifiBlinkHalfMs = 400;

}  // namespace

void LedDevice::begin() {
    pinMode(kGreenPin, OUTPUT);
    pinMode(kRedPin, OUTPUT);
    digitalWrite(kGreenPin, LOW);
    digitalWrite(kRedPin, LOW);
    buzzer_.begin();
    wifiDisconnectedSinceMs_ = millis();
}

void LedDevice::setWifiConnected(bool connected, uint32_t now) {
    if (connected == wifiConnected_) return;
    wifiConnected_ = connected;
    if (!connected) {
        wifiDisconnectedSinceMs_ = now;
        buzzer_.setState(resilience::LedState::Idle, now);
    } else if (controller_.state() == resilience::LedState::Recognized) {
        buzzer_.setState(resilience::LedState::Recognized, now);
    }
}

void LedDevice::setState(resilience::LedState state, uint32_t now) {
    controller_.setState(state, now);
    if (wifiConnected_) buzzer_.setState(state, now);
    tick(now);
}

void LedDevice::tick(uint32_t now) {
    resilience::LedOutput output = controller_.update(now);
    if (!wifiConnected_) {
        const bool red = ((now - wifiDisconnectedSinceMs_) / kWifiBlinkHalfMs) % 2u == 0u;
        output = {red ? resilience::LedColor::Red : resilience::LedColor::Green, true};
    }
    digitalWrite(kGreenPin, output.color == resilience::LedColor::Green && output.on ? HIGH : LOW);
    digitalWrite(kRedPin, output.color == resilience::LedColor::Red && output.on ? HIGH : LOW);
    if (controller_.state() == resilience::LedState::Idle) {
        buzzer_.setState(resilience::LedState::Idle, now);
    } else {
        buzzer_.tick(now);
    }
}
