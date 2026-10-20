#pragma once

#include <cstdint>

namespace resilience {

enum class LedState { Idle, Recognized, AuthOk, AuthFail, NotRecognized };
enum class LedColor { Off, Green, Red };

// Valeur inconnue : false, sans modifier `out`.
bool led_state_from_string(const char* value, LedState& out);

struct LedOutput {
    LedColor color;
    bool on;
};

struct LedTimings {
    uint32_t green_blink_half = 400;
    uint32_t red_blink_half = 150;
    uint8_t red_blink_count = 10;
    uint32_t green_solid_ms = 30000;
    uint32_t red_solid_ms = 30000;
};

// Logique pure : aucune dépendance à Arduino ou au transport réseau.
class LedController {
  public:
    explicit LedController(LedTimings timings = {});

    void setState(LedState state, uint32_t nowMs);
    LedState state() const;
    LedOutput update(uint32_t nowMs);

  private:
    static bool blinkOn(uint32_t elapsed, uint32_t halfPeriod);

    LedTimings timings_;
    LedState state_ = LedState::Idle;
    uint32_t startMs_ = 0;
};

}  // namespace resilience
