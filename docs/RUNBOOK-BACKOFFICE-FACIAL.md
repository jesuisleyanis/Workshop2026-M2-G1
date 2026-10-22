# Runbook — back-office à reconnaissance faciale + LED ESP8266 (PC Hôte)

Procédure pour lever la démo de la Consigne Additionnelle 1 sur le **PC Hôte** : identifiant →
visage (caméra USB de l'hôte, 3 poses dans un ordre aléatoire) → mot de passe, avec la LED
bicolore de l'ESP8266 pilotée en MQTT. Détails : [`consigne-additionnelle-1.md`](consigne-additionnelle-1.md),
contrat [`contracts.md` §5](contracts.md), ADR [0007](adr/0007-acces-hote-vivacite-poses-photos-chiffrees.md).

## 0. Prérequis (une fois)

| Élément | Attendu |
|---|---|
| Docker Desktop | démarré (moteur WSL2). Compose ≥ 2.20 (`docker compose version`). |
| sops + age | installés ; clé privée age de l'équipe dans `~/.config/sops/age/keys.txt` (jamais commitée). |
| `make` | WSL ou Git Bash + make. Sans make : les commandes `docker compose` équivalentes sont données ci-dessous. |
| Caméra USB | branchée **sur ce PC** (le back-office n'est joignable que depuis lui). |
| Point d'accès Windows | Paramètres → Réseau et Internet → Point d'accès sans fil mobile. **Nom et mot de passe = ceux flashés dans l'ESP** (`iot/esp8266-led/include/secrets.h`, transmis hors git). IP de l'hôte sur ce réseau : `192.168.137.1`. |
| ESP8266 | flashé (CLion + PlatformIO, voir [`iot/esp8266-led/README.md`](../iot/esp8266-led/README.md)), alimenté. `MQTT_PASSWORD` du firmware = `MQTT_LED_PASSWORD` de SOPS. |

## 1. Lancer la stack

```bash
git pull
# Activer le point d'accès AVANT : le broker se publie sur 192.168.137.1
make up-iot          # = make decrypt + docker compose --profile demo --profile iot up -d --build
```

Sans make :

```bash
scripts/decrypt-secrets.sh            # produit .env (+ .env.local la 1re fois, voir §4)
docker compose -f infra/compose/docker-compose.yml --env-file .env --profile demo --profile iot up -d --build
```

Le premier build compile **dlib** pour `face-id` (≈ 5 à 10 min) et télécharge le modèle MediaPipe
du back-office (réseau requis). Vérifier : `docker compose -f infra/compose/docker-compose.yml ps`
→ `face-id`, `auth`, `backoffice`, `waf`, `mosquitto` en `healthy`.

## 2. Premier démarrage : créer l'administrateur

1. Ouvrir **https://localhost:9443** dans Chrome **sur le PC Hôte** (certificat auto-signé du WAF :
   « Paramètres avancés → Continuer »). Autoriser la caméra.
2. L'écran **Initialisation du back-office** s'affiche (aucun admin enrôlé). Saisir :
   - le **jeton d'initialisation** : clé `BACKOFFICE_BOOTSTRAP_TOKEN` du fichier `.env` (ou `.env.local`) ;
   - un identifiant **nouveau** (un compte client existant est refusé) et un mot de passe (≥ 8 caractères).
3. Le scanner demande **Face → Profil gauche → Profil droit** : tenir chaque pose ~1 s, la capture est automatique.
4. Valider : le compte admin est créé, visage lié (gabarits + photos chiffrés AES-256 en base).

## 3. Se connecter avec le visage

1. Identifiant → **Continuer** : la caméra s'allume, LED éteinte.
2. Faire les **3 poses dans l'ordre affiché** (tiré au hasard à chaque connexion).
3. Visage reconnu → **LED verte clignotante** → saisir le mot de passe.
4. Mot de passe correct → **LED verte fixe 30 s** puis éteinte → écran **Habilitations**.

| Situation | LED (physique + jumeau à l'écran) | Comportement |
|---|---|---|
| Visage non reconnu | **rouge fixe 30 s** | caméra coupée à la fin, identifiant vidé ; 1 reprise puis **blocage 5 min** |
| Mot de passe faux | **rouge clignotant ×10** (3 s) | retour à l'identifiant |
| Succès | **vert fixe 30 s** | back-office disponible |

Dans **Habilitations** : « Nouvel agent » (identifiant, mot de passe, rôle, 3 poses), changement de
rôle, photos, réenrôlement, révocation. Le dernier admin enrôlé ne peut être ni rétrogradé ni révoqué.

Le **front client** (https://localhost, comptes `demo01…`, mot de passe `SEED_PASSWORD`, après `make seed`)
reste en identifiant + mot de passe : le visage ne concerne que le back-office.

## 4. Secrets propres au PC Hôte

`FACE_INTERNAL_TOKEN`, `FACE_DATA_KEY`, `BACKOFFICE_BOOTSTRAP_TOKEN` : s'ils ne sont pas dans
`security/sops/secrets.enc.env`, `scripts/ensure-local-secrets.sh` (appelé par `make decrypt`) les
génère **une fois** dans `.env.local` (0600, ignoré par git). **Ne pas supprimer `.env.local`** :
perdre `FACE_DATA_KEY` rend les enrôlements illisibles (il faudra réenrôler, voir `pca-pra.md` §5.7).
Pour les figer en équipe : `sops security/sops/secrets.enc.env` et y recopier les trois valeurs.

## 5. Vérifier la LED

- Pastille « **Module LED en ligne** » sur l'écran de connexion = l'ESP a publié `{"online":true}` sur
  `resilience/led/status` (via le broker).
- Test manuel depuis l'hôte (l'ESP doit réagir) :

```bash
docker compose -f infra/compose/docker-compose.yml exec mosquitto \
  sh -c 'mosquitto_pub -h 127.0.0.1 -u auth -P "$MQTT_AUTH_PASSWORD" -t resilience/led/cmd -q 1 \
         -m "{\"state\":\"recognized\",\"ts\":\"2026-01-01T00:00:00Z\",\"challenge_id\":null}"'
```

(`auth` publie normalement ces états lui-même ; `idle` pour éteindre.)

## 6. Dépannage

| Symptôme | Cause / action |
|---|---|
| `mosquitto` ne démarre pas (`cannot assign requested address`) | point d'accès non activé (pas d'IP 192.168.137.1). L'activer puis `make up-iot`. Sur un poste de dev sans hotspot : `MQTT_BIND_ADDR=127.0.0.1` dans `.env`. |
| Pastille « Module LED hors ligne / inconnu » | ESP hors hotspot (SSID/mot de passe différents de ceux flashés) ou `MQTT_LED_PASSWORD` ≠ mot de passe du firmware (`docker compose logs mosquitto` → `not authorised`). |
| « Service de reconnaissance indisponible » | `face-id` pas encore `healthy` (chargement dlib) : `docker compose logs face-id`. |
| Profils jamais capturés | tourner davantage la tête (marges 0.07 / 0.22, à calibrer) ; bonne lumière, un seul visage. |
| Bloqué 5 min pendant les essais | `docker compose -f infra/compose/docker-compose.yml restart auth` (verrous en mémoire). |
| Docker Desktop ne démarre pas (`userAnalyticsOtlpHttp.sock`) | quitter Docker Desktop, renommer `%LOCALAPPDATA%\Docker\run` puis relancer. |
| Repartir de zéro (base + enrôlements) | `make down` puis `docker volume rm resilience-g1_pgdata` (perte de toutes les données). |
