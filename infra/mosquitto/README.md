# mosquitto — broker MQTT du pilotage LED (consigne additionnelle 1)

Broker durci qui transporte les états d'authentification du PC Hôte vers l'objet connecté ESP8266
(ADR [0006](../../docs/adr/0006-led-mqtt-etats-semantiques.md), contrat §5.3).
Le service `mosquitto` est dans `infra/compose/docker-compose.yml`, profil `iot`, consommé par `auth`
(publication des commandes LED, lecture du statut pour le jumeau LED du back-office).

## Démarrer

Ajouter `MQTT_AUTH_PASSWORD` et `MQTT_LED_PASSWORD` au fichier SOPS chiffré à partir du
[modèle](../../security/sops/secrets.example.env), puis démarrer le PA Windows
`RESILIENCE-G1` (`192.168.137.1`) et lancer depuis la racine du dépôt :

```bash
make up-iot
docker compose -f infra/compose/docker-compose.yml --profile iot ps mosquitto
```

Le profil `iot` est séparé de `make up` : la publication du port exige que l'adresse
`192.168.137.1` existe déjà sur l'hôte (hors hotspot, poste de dev : `MQTT_BIND_ADDR=127.0.0.1`).
Sans le profil `iot`, `auth` démarre quand même (dépendance `required: false`) et la LED est
simplement indisponible (notifieur fail-open). Le compte `led` et son mot de passe doivent
être reportés dans `iot/esp8266-led/include/secrets.h` (fichier non versionné).

## Durcissement (points sondés)

- `allow_anonymous false` + `password_file` : aucun accès anonyme.
- `acl_file` : moindre privilège par topic —
  - `auth` **écrit** `resilience/led/cmd` et **lit** `resilience/led/status` (jumeau LED du
    back-office, `GET /api/v1/auth/device`) ;
  - l'objet `led` (ESP8266) **lit** `cmd` et **écrit** `resilience/led/status` (heartbeat + LWT).
- **Bind hotspot uniquement** : le port est publié sur l'IP du PA seulement —
  `"${MQTT_BIND_ADDR:-192.168.137.1}:1883:1883"` (jamais `0.0.0.0`). C'est le seul ingress MQTT,
  comme le WAF est le seul ingress HTTP. `auth` joint le broker en interne via `mosquitto:1883`
  (réseau `app`).
- Conteneur durci (image épinglée, UID/GID 1883, `cap_drop: ALL`, `read_only`,
  config en lecture seule, healthcheck du port) — parité avec le reste de la stack.
- Secrets : [`entrypoint.sh`](entrypoint.sh) produit `passwd` dans le tmpfs `/run/mosquitto` depuis
  les deux mots de passe SOPS (échec immédiat si l'un manque). L'ACL y est copiée avec les
  permissions de l'utilisateur Mosquitto. Aucun fichier déchiffré n'est créé dans le dépôt.
- TLS (8883) reste optionnel en laboratoire ; le trafic MQTT circule sur le PA du groupe.

## Vérifier les droits

```bash
# Depuis le PC Hôte, avec les secrets chargés dans l'environnement :
mosquitto_pub -h 192.168.137.1 -u auth -P "$MQTT_AUTH_PASSWORD" \
  -t resilience/led/cmd -m '{"state":"recognized"}'
mosquitto_sub -h 192.168.137.1 -u auth -P "$MQTT_AUTH_PASSWORD" \
  -C 1 -W 3 -t resilience/led/status -v
```

`auth` peut publier `cmd` et lire `status` ; `led` peut lire `cmd` et publier `status`. Les
commandes directes HTTP de l'ESP8266 restent indépendantes de ce broker.
