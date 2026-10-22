#pragma once

#include <Arduino.h>
#include <led_controller.h>

class Buzzer {
  public:
    void begin();
    void setState(resilience::LedState state, uint32_t now);
    void tick(uint32_t now);

  private:
    enum class Pattern { Silent, Waiting, Success, Error, Circus };

    void playStep();

    Pattern pattern_ = Pattern::Silent;
    uint8_t step_ = 0;
    uint32_t stepStartedMs_ = 0;
};
