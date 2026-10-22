#pragma once

#include <Arduino.h>
#include <led_controller.h>

class LedDevice {
  public:
    void begin();
    void setState(resilience::LedState state, uint32_t now);
    void tick(uint32_t now);

  private:
    resilience::LedController controller_;
};
