// Tests unitaires de la machine à états LED (exécutés sur PC : `pio test -e native`).
// Couvre les 5 états du contrat §5.3, les timings (vert fixe 30 s, rouge ×10, rouge fixe 30 s),
// le défaut éteint, l'auto-extinction, et le parseur d'état MQTT.

#include <led_controller.h>
#include <unity.h>

using resilience::LedColor;
using resilience::LedController;
using resilience::LedState;
using resilience::led_state_from_string;

// Unity caste en entier : une `enum class` n'a pas de conversion implicite, on caste
// explicitement (sinon la comparaison ne compile pas).
#define ASSERT_ENUM(expected, actual) \
    TEST_ASSERT_EQUAL_INT(static_cast<int>(expected), static_cast<int>(actual))

void test_default_is_off() {
    LedController led;  // état initial = Idle
    auto out = led.update(0);
    ASSERT_ENUM(LedState::Idle, led.state());
    TEST_ASSERT_FALSE(out.on);
    ASSERT_ENUM(LedColor::Off, out.color);
}

void test_recognized_blinks_green_indefinitely() {
    LedController led;
    led.setState(LedState::Recognized, 1000);
    // Première demi-période : vert allumé ; demi-période suivante : éteint ; couleur verte.
    auto a = led.update(1000);
    auto b = led.update(1000 + 400);
    ASSERT_ENUM(LedColor::Green, a.color);
    TEST_ASSERT_TRUE(a.on);
    TEST_ASSERT_FALSE(b.on);
    // Toujours en clignotement longtemps après (pas d'extinction automatique).
    auto c = led.update(1000 + 60000);
    ASSERT_ENUM(LedState::Recognized, led.state());
    ASSERT_ENUM(LedColor::Green, c.color);
}

void test_auth_ok_is_solid_green_then_off_after_30s() {
    LedController led;
    led.setState(LedState::AuthOk, 0);
    auto mid = led.update(15000);
    ASSERT_ENUM(LedColor::Green, mid.color);
    TEST_ASSERT_TRUE(mid.on);  // fixe, pas de clignotement
    TEST_ASSERT_TRUE(led.update(29999).on);
    auto after = led.update(30000);  // 30 s écoulées -> éteint
    TEST_ASSERT_FALSE(after.on);
    ASSERT_ENUM(LedState::Idle, led.state());
}

void test_auth_fail_blinks_red_ten_times_then_off() {
    LedController led;  // rouge : demi-période 150 ms, 10 clignotements -> 3000 ms
    led.setState(LedState::AuthFail, 0);
    auto first = led.update(0);
    ASSERT_ENUM(LedColor::Red, first.color);
    TEST_ASSERT_TRUE(first.on);
    TEST_ASSERT_FALSE(led.update(150).on);   // seconde moitié du 1er cycle
    TEST_ASSERT_TRUE(led.update(300).on);    // début du 2e cycle
    ASSERT_ENUM(LedColor::Red, led.update(2999).color);  // encore en séquence
    auto after = led.update(3000);  // 10 clignotements terminés -> éteint
    TEST_ASSERT_FALSE(after.on);
    ASSERT_ENUM(LedState::Idle, led.state());
}

void test_not_recognized_is_solid_red_then_off_after_30s() {
    LedController led;
    led.setState(LedState::NotRecognized, 500);
    auto mid = led.update(500 + 10000);
    ASSERT_ENUM(LedColor::Red, mid.color);
    TEST_ASSERT_TRUE(mid.on);
    auto after = led.update(500 + 30000);
    TEST_ASSERT_FALSE(after.on);
    ASSERT_ENUM(LedState::Idle, led.state());
}

void test_state_parser_maps_contract_strings() {
    LedState s;
    TEST_ASSERT_TRUE(led_state_from_string("idle", s));
    ASSERT_ENUM(LedState::Idle, s);
    TEST_ASSERT_TRUE(led_state_from_string("recognized", s));
    ASSERT_ENUM(LedState::Recognized, s);
    TEST_ASSERT_TRUE(led_state_from_string("auth_ok", s));
    ASSERT_ENUM(LedState::AuthOk, s);
    TEST_ASSERT_TRUE(led_state_from_string("auth_fail", s));
    ASSERT_ENUM(LedState::AuthFail, s);
    TEST_ASSERT_TRUE(led_state_from_string("not_recognized", s));
    ASSERT_ENUM(LedState::NotRecognized, s);
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
