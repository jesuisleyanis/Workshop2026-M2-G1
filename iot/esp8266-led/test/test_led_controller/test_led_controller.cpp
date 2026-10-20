// Tests unitaires de la machine à états LED (exécutés sur PC : `pio test -e native`).
// Couvre les 5 états du contrat §5.3, les timings (vert fixe 30 s, rouge ×10, rouge fixe 30 s),
// le défaut éteint, l'auto-extinction, et le parseur d'état MQTT.

#include <led_controller.h>
#include <unity.h>

using resilience::LedColor;
using resilience::LedController;
using resilience::LedState;
using resilience::led_state_from_string;

void test_default_is_off() {
    LedController led;  // état initial = Idle
    auto out = led.update(0);
    TEST_ASSERT_EQUAL(LedState::Idle, led.state());
    TEST_ASSERT_FALSE(out.on);
    TEST_ASSERT_EQUAL(LedColor::Off, out.color);
}

void test_recognized_blinks_green_indefinitely() {
    LedController led;
    led.setState(LedState::Recognized, 1000);
    // Première demi-période : vert allumé ; demi-période suivante : éteint ; couleur verte.
    auto a = led.update(1000);
    auto b = led.update(1000 + 400);
    TEST_ASSERT_EQUAL(LedColor::Green, a.color);
    TEST_ASSERT_TRUE(a.on);
    TEST_ASSERT_FALSE(b.on);
    // Toujours en clignotement longtemps après (pas d'extinction automatique).
    auto c = led.update(1000 + 60000);
    TEST_ASSERT_EQUAL(LedState::Recognized, led.state());
    TEST_ASSERT_EQUAL(LedColor::Green, c.color);
}

void test_auth_ok_is_solid_green_then_off_after_30s() {
    LedController led;
    led.setState(LedState::AuthOk, 0);
    auto mid = led.update(15000);
    TEST_ASSERT_EQUAL(LedColor::Green, mid.color);
    TEST_ASSERT_TRUE(mid.on);  // fixe, pas de clignotement
    TEST_ASSERT_TRUE(led.update(29999).on);
    auto after = led.update(30000);  // 30 s écoulées -> éteint
    TEST_ASSERT_FALSE(after.on);
    TEST_ASSERT_EQUAL(LedState::Idle, led.state());
}

void test_auth_fail_blinks_red_ten_times_then_off() {
    LedController led;  // rouge : demi-période 150 ms, 10 clignotements -> 3000 ms
    led.setState(LedState::AuthFail, 0);
    auto first = led.update(0);
    TEST_ASSERT_EQUAL(LedColor::Red, first.color);
    TEST_ASSERT_TRUE(first.on);
    TEST_ASSERT_FALSE(led.update(150).on);   // seconde moitié du 1er cycle
    TEST_ASSERT_TRUE(led.update(300).on);    // début du 2e cycle
    TEST_ASSERT_TRUE(led.update(2999).color == LedColor::Red);  // encore en séquence
    auto after = led.update(3000);  // 10 clignotements terminés -> éteint
    TEST_ASSERT_FALSE(after.on);
    TEST_ASSERT_EQUAL(LedState::Idle, led.state());
}

void test_not_recognized_is_solid_red_then_off_after_30s() {
    LedController led;
    led.setState(LedState::NotRecognized, 500);
    auto mid = led.update(500 + 10000);
    TEST_ASSERT_EQUAL(LedColor::Red, mid.color);
    TEST_ASSERT_TRUE(mid.on);
    auto after = led.update(500 + 30000);
    TEST_ASSERT_FALSE(after.on);
    TEST_ASSERT_EQUAL(LedState::Idle, led.state());
}

void test_state_parser_maps_contract_strings() {
    LedState s;
    TEST_ASSERT_TRUE(led_state_from_string("idle", s));
    TEST_ASSERT_EQUAL(LedState::Idle, s);
    TEST_ASSERT_TRUE(led_state_from_string("recognized", s));
    TEST_ASSERT_EQUAL(LedState::Recognized, s);
    TEST_ASSERT_TRUE(led_state_from_string("auth_ok", s));
    TEST_ASSERT_EQUAL(LedState::AuthOk, s);
    TEST_ASSERT_TRUE(led_state_from_string("auth_fail", s));
    TEST_ASSERT_EQUAL(LedState::AuthFail, s);
    TEST_ASSERT_TRUE(led_state_from_string("not_recognized", s));
    TEST_ASSERT_EQUAL(LedState::NotRecognized, s);
    // Valeur inconnue -> refusée (fail-safe : on ne change pas d'état).
    TEST_ASSERT_FALSE(led_state_from_string("bogus", s));
    TEST_ASSERT_FALSE(led_state_from_string(nullptr, s));
}

int main(int, char**) {
    UNITY_BEGIN();
    RUN_TEST(test_default_is_off);
    RUN_TEST(test_recognized_blinks_green_indefinitely);
    RUN_TEST(test_auth_ok_is_solid_green_then_off_after_30s);
    RUN_TEST(test_auth_fail_blinks_red_ten_times_then_off);
    RUN_TEST(test_not_recognized_is_solid_red_then_off_after_30s);
    RUN_TEST(test_state_parser_maps_contract_strings);
    return UNITY_END();
}
