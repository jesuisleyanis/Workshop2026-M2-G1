# mosquitto — broker MQTT du pilotage LED (consigne additionnelle 1)

Broker durci qui transporte les états d'authentification du PC Hôte vers l'objet connecté ESP8266
(ADR [0006](../../docs/adr/0006-led-mqtt-etats-semantiques.md), contrat §5.3).
Le service `mosquitto` est dans `infra/compose/docker-compose.yml`, profil `iot`.

## Démarrer

Ajouter `MQTT_AUTH_PASSWORD` et `MQTT_LED_PASSWORD` au fichier SOPS chiffré à partir du
[modèle](../../security/sops/secrets.example.env), puis démarrer le PA Windows
`RESILIENCE-G1` (`192.168.137.1`) et lancer depuis la racine du dépôt :

```bash
make up-iot
docker compose -f infra/compose/docker-compose.yml --profile iot ps mosquitto
```

Le profil `iot` est séparé de `make up` : la publication du port exige que l'adresse
`192.168.137.1` existe déjà sur l'hôte. Le compte `led` et son mot de passe doivent
être reportés dans `iot/esp8266-led/include/secrets.h` (fichier non versionné).

## Durcissement (points sondés)

- `allow_anonymous false` + `password_file` : aucun accès anonyme.
- `acl_file` : moindre privilège par topic — `auth` **écrit** `resilience/led/cmd` ; l'objet `led`
  **lit** `cmd` et **écrit** `resilience/led/status` (heartbeat + LWT).
- **Bind hotspot uniquement** : au niveau Docker, publier le port sur l'IP du PA seulement —
  `ports: ["192.168.137.1:1883:1883"]` (jamais `0.0.0.0`). C'est le seul ingress MQTT, comme le
  WAF est le seul ingress HTTP.
- Conteneur durci (image épinglée, UID/GID 1883, `cap_drop: ALL`, `read_only`,
  config en lecture seule, healthcheck du port) — parité avec le reste de la stack.
- Secrets : `entrypoint.sh` produit `passwd` dans le tmpfs `/run/mosquitto` depuis les
  deux mots de passe SOPS. L'ACL y est copiée avec les permissions de l'utilisateur
  Mosquitto. Aucun fichier déchiffré n'est créé dans le dépôt.
- TLS (8883) reste optionnel en laboratoire ; le trafic MQTT circule sur le PA du groupe.

## Vérifier les droits

```bash
# Depuis le PC Hôte, avec les secrets chargés dans l'environnement :
mosquitto_pub -h 192.168.137.1 -u auth -P "$MQTT_AUTH_PASSWORD" \
  -t resilience/led/cmd -m '{"state":"recognized"}'
```

`auth` peut publier `cmd` ; `led` peut le lire et publier `status`. Les commandes
directes HTTP de l'ESP8266 restent indépendantes de ce broker.
