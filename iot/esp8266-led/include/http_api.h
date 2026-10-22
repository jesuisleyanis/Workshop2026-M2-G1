#pragma once

#include <ESP8266WebServer.h>

#include "led_device.h"

class HttpApi {
  public:
    explicit HttpApi(LedDevice& led);

    void begin();
    void tick(bool wifiConnected);

  private:
    void command(resilience::LedState state);

    LedDevice& led_;
    ESP8266WebServer server_{80};
};
