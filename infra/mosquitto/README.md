# mosquitto — broker MQTT du pilotage LED (consigne additionnelle 1)

Broker durci qui transporte les états d'authentification du PC Hôte vers l'objet connecté ESP8266
(ADR [0006](../../docs/adr/0006-led-mqtt-etats-semantiques.md), contrat §5.3). **Statut : service
Compose `mosquitto` câblé** (`infra/compose/docker-compose.yml`), consommé par `auth`.

## Durcissement (points sondés)

- `allow_anonymous false` + `password_file` : aucun accès anonyme.
- `acl_file` : moindre privilège par topic —
  - `auth` **écrit** `resilience/led/cmd`, **lit** `resilience/led/status` (jumeau LED du back-office) et
    `$SYS/broker/uptime` (sonde de vie Compose uniquement) ;
  - l'objet `led` (ESP8266) **lit** `cmd` et **écrit** `resilience/led/status` (heartbeat + LWT).
- **Bind hotspot uniquement** : le port est publié sur l'IP du PA seulement —
  `"${MQTT_BIND:-192.168.137.1}:1883:1883"` (jamais `0.0.0.0`). C'est le seul ingress MQTT, comme le
  WAF est le seul ingress HTTP. `auth` joint le broker en interne via `mosquitto:1883` (réseau `app`).
- Conteneur durci : image épinglée (`eclipse-mosquitto:2.0.20`), `user: 1883:1883`, `cap_drop: ALL`,
  `no-new-privileges`, racine `read_only`, config montée en `:ro`, healthcheck `mosquitto_sub`.

## Fichier de mots de passe : généré au démarrage, jamais sur disque

Le `password_file` (`/mosquitto/run/passwd`) n'est **ni commité ni dans un volume** : l'entrypoint
[`docker-entrypoint.sh`](docker-entrypoint.sh) le crée à chaque démarrage dans un **tmpfs**
(`/mosquitto/run`, propriété de l'uid 1883, mode 0700) à partir des secrets SOPS injectés par Compose :

```bash
mosquitto_passwd -b -c /mosquitto/run/passwd auth "$MQTT_AUTH_PASSWORD"   # auth : publie cmd, lit status
mosquitto_passwd -b    /mosquitto/run/passwd led  "$MQTT_LED_PASSWORD"    # led : compte de l'ESP8266
exec mosquitto -c /mosquitto/config/mosquitto.conf
```

Si `MQTT_AUTH_PASSWORD` ou `MQTT_LED_PASSWORD` est vide, l'entrypoint **échoue immédiatement** (pas de
broker sans identifiants). L'ESP8266 se connecte avec l'utilisateur `led` et `MQTT_LED_PASSWORD`.
Les variables sont documentées dans [`security/sops/secrets.example.env`](../../security/sops/secrets.example.env).

## Service Compose

Voir le service `mosquitto` de `infra/compose/docker-compose.yml` : volumes `mosquitto.conf`, `aclfile` et
`docker-entrypoint.sh` en `:ro`, `tmpfs: ["/mosquitto/run:uid=1883,gid=1883,mode=0700"]`, `entrypoint`
`/bin/sh /mosquitto/docker-entrypoint.sh`. TLS (8883) reste optionnel (voir `mosquitto.conf`).

## Vérification manuelle (Docker requis)

```bash
docker compose -f infra/compose/docker-compose.yml up -d mosquitto
docker compose -f infra/compose/docker-compose.yml exec mosquitto \
  sh -c 'mosquitto_sub -h 127.0.0.1 -u auth -P "$MQTT_AUTH_PASSWORD" -C 1 -W 3 -t resilience/led/status -v'
```
