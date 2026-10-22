#pragma once

#include <ESP8266WiFi.h>
#include <PubSubClient.h>

#include "led_device.h"

class MqttBridge {
  public:
    explicit MqttBridge(LedDevice& led);

    void begin();
    void tick(uint32_t now, bool wifiConnected);

  private:
    void onMessage(char* topic, uint8_t* payload, unsigned int length);
    void connect(uint32_t now);

    LedDevice& led_;
    WiFiClient client_;
    PubSubClient mqtt_{client_};
    uint32_t lastAttemptMs_ = 0;
    uint32_t lastHeartbeatMs_ = 0;
    bool attempted_ = false;
};
