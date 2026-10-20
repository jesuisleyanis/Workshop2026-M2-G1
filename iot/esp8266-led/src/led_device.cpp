#include "led_device.h"

namespace {

// LED bicolore à cathode commune : une sortie par couleur, avec résistances.
constexpr uint8_t kGreenPin = D1;
constexpr uint8_t kRedPin = D2;

}  // namespace

void LedDevice::begin() {
    pinMode(kGreenPin, OUTPUT);
    pinMode(kRedPin, OUTPUT);
    digitalWrite(kGreenPin, LOW);
    digitalWrite(kRedPin, LOW);
}

void LedDevice::setState(resilience::LedState state, uint32_t now) {
    controller_.setState(state, now);
    tick(now);
}

void LedDevice::tick(uint32_t now) {
    const resilience::LedOutput output = controller_.update(now);
    digitalWrite(kGreenPin, output.color == resilience::LedColor::Green && output.on ? HIGH : LOW);
    digitalWrite(kRedPin, output.color == resilience::LedColor::Red && output.on ? HIGH : LOW);
}
