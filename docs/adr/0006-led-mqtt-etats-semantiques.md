# ADR 0006 — Pilotage LED via MQTT, états sémantiques publiés par `auth`

- **Statut :** accepté (Consigne Additionnelle 1, 2026-10-20)
- **Contexte :** la consigne ajoute un objet connecté **ESP8266 + LED bicolore** connecté en **WiFi au PA** (`192.168.137.0/24`), piloté par la phase d'authentification. Les conteneurs sont sur des réseaux Docker **internes** ; l'ESP est sur le **hotspot**. Il faut un point de rencontre réseau, et décider où vit la logique de motif/timing de la LED.
- **Décision :**
  1. **Transport = MQTT (Mosquitto).** Un broker durci est **bindé sur l'interface hotspot uniquement** (comme le WAF est le seul ingress HTTP, le broker est le seul ingress MQTT), `allow_anonymous false`, authentifié (creds SOPS), **ACL par topic** (`auth` publie `resilience/led/cmd`, l'ESP souscrit `cmd` et publie `resilience/led/status`).
  2. **`auth` publie des états sémantiques** (`idle|recognized|auth_ok|auth_fail|not_recognized`) ; le **firmware** mappe chaque état vers son **motif + timing** (vert fixe 30 s, rouge clignotant ×10, etc. — contrat §5.3). Le contrat réseau reste minimal.
  3. **Publication fail-open :** un broker ou un ESP injoignable n'empêche **jamais** la connexion (la LED est un témoin, pas un facteur). L'échec est journalisé (`led_publish_failed`).
  4. **Portée du facteur (D4) :** le visage et la LED ne renforcent que l'**accès privilégié** du back-office ; la boucle Zero-Touch Recovery (`verify_tx`, détection, remédiation, Clip Chrono) n'en dépend jamais — pas d'auto-DoS de la démo notée.
- **Alternatives écartées :**
  - *ESP en serveur HTTP* (auth POSTe l'état sur l'IP de l'ESP) — auth devrait connaître/suivre l'IP de l'objet et franchir la frontière réseau ; plus fragile.
  - *Service `led-bridge` dédié* entre auth et MQTT — sur-découpage pour ce périmètre ; gardé comme option de montée en charge si l'on veut sortir le client MQTT de `auth`.
  - *Timing côté serveur* (auth tient le « 30 s » / « ×10 ») — alourdit le contrat et couple le serveur à l'objet ; le firmware autonome est plus robuste aux coupures.
- **Conséquences :**
  - (+) Découplage net, testable (auth : publication mockée ; firmware : machine à états en test `native`).
  - (+) Surface réseau ajoutée **maîtrisée et documentée** (un seul topic de commande, ACL, bind hotspot) — portée en risque résiduel EBIOS.
  - (−) Un broker de plus à durcir et à superviser (LWT → disponibilité de l'objet).
