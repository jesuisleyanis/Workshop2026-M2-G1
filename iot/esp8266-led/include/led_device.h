#pragma once

#include <Arduino.h>
#include <led_controller.h>

#include "buzzer.h"

class LedDevice {
  public:
    void begin();
    void setWifiConnected(bool connected, uint32_t now);
    void setState(resilience::LedState state, uint32_t now);
    void tick(uint32_t now);

  private:
    resilience::LedController controller_;
    Buzzer buzzer_;
    bool wifiConnected_ = false;
    uint32_t wifiDisconnectedSinceMs_ = 0;
};
