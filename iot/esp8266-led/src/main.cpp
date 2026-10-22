#include <Arduino.h>

#include "http_api.h"
#include "led_device.h"
#include "mqtt_bridge.h"
#include "wifi_connection.h"

namespace {

LedDevice led;
WifiConnection wifi;
HttpApi http(led);
MqttBridge mqtt(led);

}  // namespace

void setup() {
    Serial.begin(74880);
    Serial.println();
    Serial.println("ESP8266 LED starting");
    led.begin();
    wifi.begin();
    http.begin();
    mqtt.begin();
}

void loop() {
    const uint32_t now = millis();
    wifi.tick(now);
    const bool connected = wifi.connected();
    led.setWifiConnected(connected, now);
    led.tick(now);
    http.tick(connected);
    mqtt.tick(now, connected);
    led.tick(millis());
}
