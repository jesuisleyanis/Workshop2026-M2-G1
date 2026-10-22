# Cahier des charges — `iot/esp8266-led`

> Composant de la **Consigne Additionnelle 1** (cadrage : [`docs/consigne-additionnelle-1.md`](../../docs/consigne-additionnelle-1.md), lot **L4**). IDE imposé : **JetBrains CLion + PlatformIO**.

## 1. Rôle

Objet connecté **ESP8266 + LED bicolore (rouge/vert)** connecté en **WiFi au point d'accès de la solution** (`RESILIENCE-G<n>`, `192.168.137.0/24`). Il matérialise physiquement la **phase d'authentification** du back-office : la LED passe au vert/rouge selon que l'opérateur est reconnu et que son mot de passe est validé (contrat §5.3).

Le firmware reçoit un **état sémantique** via MQTT ou une commande HTTP directe sur le PA, puis délègue le **motif + timing** à `resilience::LedController` (logique pure, testée sur PC). `main.cpp` orchestre les modules LED, Wi-Fi, HTTP et MQTT ; chacun a son `.h` dans `include/` et son `.cpp` dans `src/`.

## 2. Exigences couvertes

| Réf. | Exigence | Comment |
|---|---|---|
| **CA6** | ESP8266 + LED bicolore, WiFi sur le PA | `src/led_device.cpp` + `src/wifi_connection.cpp` |
| **CA7** | Machine à états LED (5 états, timings) | `lib/led/led_controller.{h,cpp}` + tests `native` |
| **CA8** | Transport des états depuis le PC Hôte | abonnement MQTT `resilience/led/cmd`, statut/LWT `resilience/led/status` |
| **Commande directe** | Déclencher les trois motifs demandés sur l'objet | `src/http_api.cpp` : trois routes POST authentifiées |
| **R13** | Secrets hors git | `include/secrets.h` (gabarit `secrets.h.example`), gitignored |

## 3. Comportement de la LED (contrat §5.3)

| État reçu (`resilience/led/cmd`) | Motif | Durée |
|---|---|---|
| `idle` | éteinte (**défaut**) | — |
| `recognized` | vert clignotant | jusqu'à l'état suivant |
| `auth_ok` | vert fixe | 30 s → éteinte |
| `auth_fail` | rouge clignotant ×10 | 12 s → éteinte |
| `not_recognized` | rouge fixe | 30 s → éteinte |

- **Non bloquant** : les motifs dérivent de `millis()` ; le Wi-Fi retente après 5 s sur échec explicite ou après 30 s si la connexion reste en cours, sans boucle d'attente.
- **Fail-safe** : payload JSON invalide ou état inconnu ⇒ aucun changement d'état ; perte WiFi/MQTT ⇒ tentative de reconnexion sans bloquer la LED.
- **Indication Wi-Fi** : hors connexion, la LED alterne rouge/vert toutes les 400 ms ; une fois connectée, elle affiche l'état d'authentification.
- **LWT** : à la déconnexion, le broker publie l'indisponibilité de l'objet (supervision côté hôte).

## 4. Câblage

LED bicolore commune **cathode** : broche verte sur **D1**, broche rouge sur **D2**, cathode au GND via résistances (~220 Ω). (Adapter les broches dans `src/led_device.cpp` selon la carte.)

Buzzer **passif** : borne positive sur **D5**, borne négative sur **GND**. Les sons suivent
les états reçus : mélodie d'attente en boucle pour `recognized`, fanfare du drapeau de Mario pour `auth_ok`,
mélodie de mort de Mario répétée pour `auth_fail`, mélodie de cirque en boucle
pour `not_recognized`.

## 5. Critères d'acceptation

| # | Critère | Vérification |
|---|---|---|
| L1 | Défaut = éteinte | `test_default_is_off` |
| L2 | `recognized` = vert clignotant sans extinction auto | `test_recognized_blinks_green_indefinitely` |
| L3 | `auth_ok` = vert fixe puis éteint à 30 s | `test_auth_ok_is_solid_green_then_off_after_30s` |
| L4 | `auth_fail` = rouge ×10 puis éteint | `test_auth_fail_blinks_red_ten_times_then_off` |
| L5 | `not_recognized` = rouge fixe puis éteint à 30 s | `test_not_recognized_is_solid_red_then_off_after_30s` |
| L6 | Parseur d'état conforme au contrat + fail-safe | `test_state_parser_maps_contract_strings` |
| L7 | Connexion WiFi au PA + réception d'un état | **recette matérielle** (checklist L10-4) |

## 6. Hors périmètre / limites assumées

- LED bicolore **2 broches** (pas de rendu simultané rouge+vert : sans objet pour cette machine à états, les états sont exclusifs).
- Pas d'OTA en v1 (flash par USB depuis CLion/PlatformIO).
- Un seul objet / une seule LED (poste d'accueil du back-office).
- Les tests `native` couvrent la **logique** (machine à états, parseur) ; la connectivité WiFi/MQTT réelle est validée en **recette** sur le PC Hôte.
