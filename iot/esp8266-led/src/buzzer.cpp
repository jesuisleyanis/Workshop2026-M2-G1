#include "buzzer.h"

namespace {

constexpr uint8_t kBuzzerPin = D5;

struct Note {
    uint16_t frequency;
    uint16_t durationMs;
};

// Petite mélodie d'attente originale, en arpèges avec une pause avant la reprise.
constexpr Note kWaiting[] = {
    {523, 240}, {659, 220}, {784, 330}, {659, 220}, {0, 100},
    {440, 240}, {523, 220}, {659, 330}, {523, 220}, {0, 100},
    {349, 240}, {440, 220}, {523, 330}, {440, 220}, {0, 100},
    {392, 240}, {494, 220}, {587, 330}, {494, 220}, {0, 100},
    {523, 480}, {0, 1800},
};
// Adaptation monophonique de la fanfare de fin de niveau (drapeau) de Mario.
// Notes et durées : https://www.nexprint.com/en/models/G0051260
constexpr Note kSuccess[] = {
    {196, 156}, {262, 156}, {330, 156}, {392, 156}, {523, 156}, {659, 156},
    {784, 413}, {659, 413},
    {208, 156}, {262, 156}, {311, 156}, {415, 156}, {523, 156}, {622, 156},
    {831, 413}, {622, 413},
    {233, 156}, {294, 156}, {349, 156}, {466, 156}, {587, 156}, {698, 156},
    {932, 413}, {0, 35}, {932, 156}, {0, 35}, {932, 156}, {0, 35},
    {932, 156}, {0, 35}, {1047, 700},
};
// Mélodie de mort de Super Mario Bros., adaptée du motif RTTTL à 90 BPM.
// Source : https://forum.arduino.cc/t/mario-theme-song-played-on-arduino-with-speaker/8471
constexpr Note kError[] = {
    {1047, 83}, {1047, 83}, {1047, 83}, {0, 333},
    {988, 167}, {1397, 167}, {0, 167}, {1397, 167},
    {1397, 250}, {1319, 250}, {1175, 167}, {1047, 167},
    {0, 167}, {659, 167}, {0, 167}, {523, 667},
    {0, 800},
};
// Thème principal de « L'Entrée des gladiateurs » de Julius Fučík (après l'introduction).
// Adapté du MIDI pour flûte : https://www.flutetunes.com/tunes.php?id=59
constexpr Note kCircus[] = {
    {1047, 134}, {0, 134}, {988, 134}, {0, 134},
    {932, 134}, {988, 134}, {932, 134}, {880, 134},
    {831, 134}, {0, 134}, {784, 134}, {0, 134},
    {740, 268}, {784, 268}, {880, 134}, {0, 134},
    {831, 134}, {0, 134}, {784, 134}, {831, 134},
    {784, 134}, {740, 134}, {698, 134}, {0, 134},
    {659, 134}, {0, 134}, {622, 268}, {659, 268},
    {784, 134}, {0, 134}, {587, 134}, {587, 134},
    {554, 268}, {587, 268}, {784, 134}, {0, 134},
    {587, 134}, {587, 134}, {554, 268}, {587, 268},
    {0, 400},
};

}  // namespace

void Buzzer::begin() {
    pinMode(kBuzzerPin, OUTPUT);
    noTone(kBuzzerPin);
}

void Buzzer::setState(resilience::LedState state, uint32_t now) {
    if (state == resilience::LedState::Idle && pattern_ == Pattern::Silent) return;
    switch (state) {
        case resilience::LedState::Recognized: pattern_ = Pattern::Waiting; break;
        case resilience::LedState::AuthOk: pattern_ = Pattern::Success; break;
        case resilience::LedState::AuthFail: pattern_ = Pattern::Error; break;
        case resilience::LedState::NotRecognized: pattern_ = Pattern::Circus; break;
        case resilience::LedState::Idle: pattern_ = Pattern::Silent; break;
    }
    step_ = 0;
    stepStartedMs_ = now;
    playStep();
}

void Buzzer::tick(uint32_t now) {
    if (pattern_ == Pattern::Silent) return;

    const Note* notes = nullptr;
    uint8_t count = 0;
    switch (pattern_) {
        case Pattern::Waiting: notes = kWaiting; count = sizeof(kWaiting) / sizeof(Note); break;
        case Pattern::Success: notes = kSuccess; count = sizeof(kSuccess) / sizeof(Note); break;
        case Pattern::Error: notes = kError; count = sizeof(kError) / sizeof(Note); break;
        case Pattern::Circus: notes = kCircus; count = sizeof(kCircus) / sizeof(Note); break;
        case Pattern::Silent: return;
    }

    if (now - stepStartedMs_ < notes[step_].durationMs) return;
    ++step_;
    if (step_ == count) {
        if (pattern_ == Pattern::Waiting || pattern_ == Pattern::Error || pattern_ == Pattern::Circus) {
            step_ = 0;
        } else {
            pattern_ = Pattern::Silent;
            noTone(kBuzzerPin);
            return;
        }
    }
    stepStartedMs_ = now;
    playStep();
}

void Buzzer::playStep() {
    const Note* notes = nullptr;
    switch (pattern_) {
        case Pattern::Waiting: notes = kWaiting; break;
        case Pattern::Success: notes = kSuccess; break;
        case Pattern::Error: notes = kError; break;
        case Pattern::Circus: notes = kCircus; break;
        case Pattern::Silent: noTone(kBuzzerPin); return;
    }
    if (notes[step_].frequency == 0) {
        noTone(kBuzzerPin);
    } else {
        tone(kBuzzerPin, notes[step_].frequency, notes[step_].durationMs);
    }
}
