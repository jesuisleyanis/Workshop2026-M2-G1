# esp8266-led — objet connecté LED bicolore (consigne additionnelle 1)

Firmware ESP8266 qui matérialise la phase d'authentification du back-office via une LED
bicolore (contrat §5.3). **IDE imposé : JetBrains CLion + PlatformIO.** Voir le
[cahier des charges](CAHIER-DES-CHARGES.md) et le [cadrage](../../docs/consigne-additionnelle-1.md).

## Préparer

```bash
cp include/secrets.h.example include/secrets.h   # NON versionné
# renseigner SSID/PSK du PA (RESILIENCE-G<n>) et les creds MQTT du broker (PC Hôte)
```

## Tester la logique (sur PC, sans matériel)

```bash
pio test -e native
```

Les tests Unity (`test/test_led_controller/`) couvrent les **5 états**, les **timings**
(vert fixe 30 s, rouge ×10, rouge fixe 30 s), le **défaut éteint** et le **parseur d'état**.
La machine à états (`lib/led/led_controller.h`) est une logique pure, isolée d'Arduino.

## Flasher la carte

```bash
pio run -e nodemcuv2 --target upload      # ou le bouton Upload de CLion/PlatformIO
pio device monitor                        # logs série (115200)
```

## Essayer de bout en bout

```bash
# Depuis le PC Hôte, publier un état (mosquitto_pub) :
mosquitto_pub -h 192.168.137.1 -u led -P "<mdp>" -t resilience/led/cmd \
  -m '{"state":"recognized","ts":"2026-10-20T10:00:00Z","challenge_id":null}'
# -> LED vert clignotant. Puis "auth_ok" -> vert fixe 30 s ; "auth_fail" -> rouge ×10.
```

En production, c'est **`auth`** qui publie ces états (fail-open : un broker injoignable n'empêche
jamais la connexion). Câblage : LED verte D1, rouge D2 (voir CDC §4).
