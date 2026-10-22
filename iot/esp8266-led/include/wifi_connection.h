#pragma once

#include <Arduino.h>

class WifiConnection {
  public:
    void begin();
    void tick(uint32_t now);
    bool connected() const;

  private:
    void tryConnect(uint32_t now);

    uint32_t lastAttemptMs_ = 0;
    bool wasConnected_ = false;
};
