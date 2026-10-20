# mosquitto — broker MQTT du pilotage LED (consigne additionnelle 1)

Broker durci qui transporte les états d'authentification du PC Hôte vers l'objet connecté ESP8266
(ADR [0006](../../docs/adr/0006-led-mqtt-etats-semantiques.md), contrat §5.3). **Statut : config
posée ; service Compose à câbler (lot L5/L7).**

## Durcissement (points sondés)

- `allow_anonymous false` + `password_file` : aucun accès anonyme.
- `acl_file` : moindre privilège par topic — `auth` **écrit** `resilience/led/cmd` ; l'objet `led`
  **lit** `cmd` et **écrit** `resilience/led/status` (heartbeat + LWT).
- **Bind hotspot uniquement** : au niveau Docker, publier le port sur l'IP du PA seulement —
  `ports: ["192.168.137.1:1883:1883"]` (jamais `0.0.0.0`). C'est le seul ingress MQTT, comme le
  WAF est le seul ingress HTTP.
- Conteneur durci (image épinglée, non-root, `cap_drop: ALL`, `read_only` + volumes config en
  lecture seule, healthcheck) — parité avec le reste de la stack (`security/hardening`).
- Secrets : le `password_file` est généré à partir de creds SOPS (`MQTT_USERNAME`/`MQTT_PASSWORD`),
  jamais commité. TLS (8883) optionnel documenté dans `mosquitto.conf`.

## Générer le fichier de mots de passe

```bash
# En recette (image mosquitto), à partir des creds SOPS :
mosquitto_passwd -b -c passwd auth "$MQTT_AUTH_PASSWORD"
mosquitto_passwd -b     passwd led  "$MQTT_LED_PASSWORD"
```

## Esquisse de service Compose (lot L7)

```yaml
mosquitto:
  image: eclipse-mosquitto:2.0.18   # épinglée (R5)
  networks: [app]                   # joignable par auth ; exposition hotspot via ports
  ports: ["192.168.137.1:1883:1883"]
  read_only: true
  cap_drop: ["ALL"]
  volumes:
    - ./infra/mosquitto/mosquitto.conf:/mosquitto/config/mosquitto.conf:ro
    - ./infra/mosquitto/aclfile:/mosquitto/config/aclfile:ro
    - mosquitto-passwd:/mosquitto/config/passwd:ro   # généré depuis SOPS
```
