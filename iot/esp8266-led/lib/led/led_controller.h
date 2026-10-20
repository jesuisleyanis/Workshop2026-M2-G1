// Machine à états de la LED bicolore (consigne additionnelle 1, contrat §5.3).
//
// Logique PURE (aucune dépendance Arduino) : le temps et le rendu physique sont injectés,
// ce qui la rend testable sur PC (`pio test -e native`). Le firmware (src/main.cpp) se contente
// de recevoir un état sémantique via MQTT, d'appeler setState(), et d'appliquer la sortie aux
// GPIO à chaque boucle. Les timings (vert fixe 30 s, rouge ×10, …) vivent ICI, pas dans le réseau.
//
// Non bloquant : aucune temporisation active, tout est dérivé de `now_ms` (millis()).

#ifndef RESILIENCE_LED_CONTROLLER_H
#define RESILIENCE_LED_CONTROLLER_H

#include <cstdint>
#include <cstring>

namespace resilience {

// États sémantiques publiés par auth (contrat §5.3).
enum class LedState { Idle, Recognized, AuthOk, AuthFail, NotRecognized };

// Traduit le champ `state` du payload MQTT (contrat §5.3) en LedState.
// Renvoie false sur une valeur inconnue (le firmware reste alors dans son état courant — fail-safe).
inline bool led_state_from_string(const char* s, LedState& out) {
    if (s == nullptr) return false;
    if (std::strcmp(s, "idle") == 0) { out = LedState::Idle; return true; }
    if (std::strcmp(s, "recognized") == 0) { out = LedState::Recognized; return true; }
    if (std::strcmp(s, "auth_ok") == 0) { out = LedState::AuthOk; return true; }
    if (std::strcmp(s, "auth_fail") == 0) { out = LedState::AuthFail; return true; }
    if (std::strcmp(s, "not_recognized") == 0) { out = LedState::NotRecognized; return true; }
    return false;
}

enum class LedColor { Off, Green, Red };

struct LedOutput {
    LedColor color;  // couleur à piloter
    bool on;         // LED allumée à cet instant (gère le clignotement)
};

// Timings (ms) — reflètent la consigne. Regroupés pour relecture et tests.
struct LedTimings {
    uint32_t green_blink_half = 400;   // vert clignotant : demi-période
    uint32_t red_blink_half = 150;     // rouge clignotant : demi-période
    uint8_t  red_blink_count = 10;     // rouge clignote 10 fois puis s'éteint
    uint32_t green_solid_ms = 30000;   // vert fixe 30 s puis s'éteint
    uint32_t red_solid_ms = 30000;     // rouge fixe 30 s puis s'éteint
};

class LedController {
  public:
    explicit LedController(LedTimings timings = {}) : timings_(timings) {}

    // Applique un nouvel état sémantique (origine = maintenant).
    void setState(LedState state, uint32_t now_ms) {
        state_ = state;
        start_ms_ = now_ms;
    }

    LedState state() const { return state_; }

    // Sortie physique à l'instant `now_ms`. Peut auto-basculer vers Idle quand une
    // séquence temporisée (vert fixe, rouge ×10, rouge fixe) est terminée.
    LedOutput update(uint32_t now_ms) {
        const uint32_t elapsed = now_ms - start_ms_;
        switch (state_) {
            case LedState::Idle:
                return {LedColor::Off, false};

            case LedState::Recognized:  // vert clignotant jusqu'à l'état suivant
                return {LedColor::Green, blink_on(elapsed, timings_.green_blink_half)};

            case LedState::AuthOk:  // vert fixe 30 s puis éteint
                if (elapsed >= timings_.green_solid_ms) {
                    state_ = LedState::Idle;
                    return {LedColor::Off, false};
                }
                return {LedColor::Green, true};

            case LedState::AuthFail: {  // rouge clignote 10 fois puis éteint
                const uint32_t total = timings_.red_blink_half * 2u * timings_.red_blink_count;
                if (elapsed >= total) {
                    state_ = LedState::Idle;
                    return {LedColor::Off, false};
                }
                return {LedColor::Red, blink_on(elapsed, timings_.red_blink_half)};
            }

            case LedState::NotRecognized:  // rouge fixe 30 s puis éteint
                if (elapsed >= timings_.red_solid_ms) {
                    state_ = LedState::Idle;
                    return {LedColor::Off, false};
                }
                return {LedColor::Red, true};
        }
        return {LedColor::Off, false};
    }

  private:
    static bool blink_on(uint32_t elapsed, uint32_t half_period) {
        // Allumé pendant la première moitié de chaque période, éteint pendant la seconde.
        return (elapsed / half_period) % 2u == 0u;
    }

    LedTimings timings_;
    LedState state_ = LedState::Idle;
    uint32_t start_ms_ = 0;
};

}  // namespace resilience

#endif  // RESILIENCE_LED_CONTROLLER_H
