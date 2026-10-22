#include "led_controller.h"

#include <cstring>

namespace resilience {

bool led_state_from_string(const char* value, LedState& out) {
    if (value == nullptr) return false;
    if (std::strcmp(value, "idle") == 0) { out = LedState::Idle; return true; }
    if (std::strcmp(value, "recognized") == 0) { out = LedState::Recognized; return true; }
    if (std::strcmp(value, "auth_ok") == 0) { out = LedState::AuthOk; return true; }
    if (std::strcmp(value, "auth_fail") == 0) { out = LedState::AuthFail; return true; }
    if (std::strcmp(value, "not_recognized") == 0) { out = LedState::NotRecognized; return true; }
    return false;
}

LedController::LedController(LedTimings timings) : timings_(timings) {}

void LedController::setState(LedState state, uint32_t nowMs) {
    state_ = state;
    startMs_ = nowMs;
}

LedState LedController::state() const {
    return state_;
}

LedOutput LedController::update(uint32_t nowMs) {
    const uint32_t elapsed = nowMs - startMs_;
    switch (state_) {
        case LedState::Idle:
            return {LedColor::Off, false};

        case LedState::Recognized:
            return {LedColor::Green, blinkOn(elapsed, timings_.green_blink_half)};

        case LedState::AuthOk:
            if (elapsed >= timings_.green_solid_ms) {
                state_ = LedState::Idle;
                return {LedColor::Off, false};
            }
            return {LedColor::Green, true};

        case LedState::AuthFail: {
            const uint32_t total = timings_.red_blink_half * 2u * timings_.red_blink_count;
            if (elapsed >= total) {
                state_ = LedState::Idle;
                return {LedColor::Off, false};
            }
            return {LedColor::Red, blinkOn(elapsed, timings_.red_blink_half)};
        }

        case LedState::NotRecognized:
            if (elapsed >= timings_.red_solid_ms) {
                state_ = LedState::Idle;
                return {LedColor::Off, false};
            }
            return {LedColor::Red, true};
    }
    return {LedColor::Off, false};
}

bool LedController::blinkOn(uint32_t elapsed, uint32_t halfPeriod) {
    return (elapsed / halfPeriod) % 2u == 0u;
}

}  // namespace resilience
