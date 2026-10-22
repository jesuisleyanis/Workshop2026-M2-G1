# esp8266-led — objet connecté LED bicolore (consigne additionnelle 1)

Firmware ESP8266 qui matérialise la phase d'authentification du back-office via une LED
bicolore (contrat §5.3). **IDE imposé : JetBrains CLion + PlatformIO.** Voir le
[cahier des charges](CAHIER-DES-CHARGES.md) et le [cadrage](../../docs/consigne-additionnelle-1.md).

## Préparer

```bash
cp include/secrets.h.example include/secrets.h   # NON versionné
# renseigner SSID/PSK du PA (RESILIENCE-G<n>), les creds MQTT du broker
# et LED_HTTP_USERNAME / LED_HTTP_PASSWORD pour les commandes HTTP
```

## Tester la logique (sur PC, sans matériel)

```bash
pio test -e native
```

Les tests Unity (`test/test_led_controller/`) couvrent les **5 états**, les **timings**
(vert fixe 30 s, rouge ×10, rouge fixe 30 s), le **défaut éteint** et le **parseur d'état**.
La machine à états (`lib/led/led_controller.h` et `.cpp`) est une logique pure,
isolée d'Arduino.

## Organisation du firmware

`src/main.cpp` initialise les composants et appelle leur boucle. Chaque module a son
interface dans `include/` et son implémentation dans `src/` :

| Module | Responsabilité |
|---|---|
| `led_device` | Broches D1/D2 et rendu de la machine à états |
| `wifi_connection` | Connexion au point d'accès, reconnexion automatique et reprise après échec |
| `http_api` | Trois commandes HTTP et authentification Basic |
| `mqtt_bridge` | Abonnement aux états, statut/LWT et heartbeat |

La connexion Wi-Fi ne contient pas de boucle d'attente : la LED continue de s'actualiser
pendant une perte de réseau. L'adresse IP est affichée sur le moniteur série après connexion.
Une tentative en cours dispose de 30 s avant d'être relancée ; les échecs explicites
peuvent être retentés après 5 s.

## Flasher la carte

```bash
pio run -e nodemcuv2 --target upload      # ou le bouton Upload de CLion/PlatformIO
pio device monitor                        # logs série (74880, y compris la ROM au boot)
```

## Essayer de bout en bout

L'ESP8266 expose trois commandes sur son adresse IP du point d'accès. Toutes demandent
une authentification HTTP Basic et répondent `204` en cas de succès :

| Requête | Effet |
|---|---|
| `POST /api/v1/led/green/blink` | Vert clignotant jusqu'à la prochaine commande |
| `POST /api/v1/led/green/solid` | Vert fixe pendant 30 s, puis extinction |
| `POST /api/v1/led/red/blink` | Rouge clignotant 10 fois, puis extinction |

```bash
curl -u 'led-control:<mot-de-passe-http-led>' -X POST \
  'http://<ip-esp8266>/api/v1/led/green/blink'
```

L'IP de l'ESP8266 est attribuée par le point d'accès ; les routes sont disponibles
uniquement lorsque la carte est connectée au Wi-Fi. La commande MQTT existante reste
disponible et utilise la même machine à états. L'authentification Basic circule en clair
sur ce réseau de démonstration : limiter son accès au PA du groupe.

Pour tester l'ancien canal MQTT, publier avec le compte `auth` (le compte `led`
n'a que le droit de lire `cmd`) :

```bash
# Depuis le PC Hôte, publier un état (mosquitto_pub) :
mosquitto_pub -h 192.168.137.1 -u auth -P "<mdp>" -t resilience/led/cmd \
  -m '{"state":"recognized","ts":"2026-10-20T10:00:00Z","challenge_id":null}'
# -> LED vert clignotant. Puis "auth_ok" -> vert fixe 30 s ; "auth_fail" -> rouge ×10.
```

En production, c'est **`auth`** qui publie ces états (fail-open : un broker injoignable n'empêche
jamais la connexion). Câblage : LED verte D1, rouge D2 (voir CDC §4).
