# Gestion des secrets — SOPS + age

> Couvre l'exigence **R13** (gestion des secrets) et la contrainte §7.4 du sujet : **aucun secret en clair dans l'archive `Code.zip`**.

## Principe

- Les secrets sont stockés **chiffrés** dans le dépôt (`secrets.enc.env`), déchiffrables uniquement avec la **clé privée age** de l'équipe, qui n'est **jamais commitée**.
- Au lancement, `scripts/decrypt-secrets.sh` produit un `.env` local (ignoré par git) consommé par Docker Compose.
- Pour la correction/jury, une **clé de démo** est fournie **hors archive** (clé USB / canal privé), jamais dans le zip.

## Secrets gérés

| Variable | Usage | Composant |
|---|---|---|
| `JWT_SECRET` | signature des JWT | auth |
| `POSTGRES_PASSWORD` | mot de passe DB | postgres, payment-api, auth |
| `REMEDIATION_TOKEN` | auth de `POST /events` | detector → remediation |
| `INTERNAL_TOKEN` | auth de `/internal/*` | remediation → auth |
| `SEED_PASSWORD` | mot de passe des comptes fictifs du seed | `make seed`, `scripts/verify_tx`, remediation (verify) |
| `FACE_INTERNAL_TOKEN` | jeton d'appel interne auth → face-id | auth, face-id |
| `FACE_DATA_KEY` | clé AES-256 (base64 de 32 octets) des gabarits/photos faciales — `python -c "import os,base64;print(base64.b64encode(os.urandom(32)).decode())"` | face-id |
| `MQTT_AUTH_PASSWORD` | mot de passe MQTT du compte `auth` (publie les commandes LED, lit l'état) | mosquitto, auth |
| `MQTT_LED_PASSWORD` | mot de passe MQTT du compte `led` (objet ESP8266 : lit les commandes, publie son statut) | mosquitto (fichier `passwd` généré au démarrage en tmpfs), firmware |
| `BACKOFFICE_BOOTSTRAP_TOKEN` | jeton d'initialisation du premier admin du back-office | auth |
| `MQTT_BIND_ADDR` | IP du hotspot sur laquelle le port 1883 est publié (profil `iot`, `make up-iot` ; non secret, défaut `192.168.137.1` ; sur une machine sans l'IP du hotspot : `MQTT_BIND_ADDR=127.0.0.1` dans **`.env.local`**, voir ci-dessous) | mosquitto |
| `GRAFANA_PASSWORD` | mot de passe admin Grafana (requis : le compose échoue sans, plus de repli `admin`) | grafana |

## Mise en place (une fois par poste)

```bash
# 1. Installer les outils
brew install sops age          # ou apt/choco selon l'OS

# 2. Générer la clé age de l'équipe (UNE fois, partagée hors git)
age-keygen -o ~/.config/sops/age/keys.txt
#   -> copier la clé PUBLIQUE (age1...) dans security/sops/.sops.yaml

# 3. Créer et chiffrer les secrets
cp security/sops/secrets.example.env security/sops/secrets.enc.env
#   éditer avec de vraies valeurs (openssl rand -hex 32 pour les tokens)
sops --encrypt --in-place security/sops/secrets.enc.env

# 4. Au lancement (fait par `make up`)
export SOPS_AGE_KEY_FILE=~/.config/sops/age/keys.txt
scripts/decrypt-secrets.sh
```

## Surcharges propres au poste : `.env.local`

`make decrypt` **régénère `.env`** depuis SOPS à chaque lancement : toute modification manuelle de
`.env` est perdue. Les valeurs propres à un poste vont dans **`.env.local`** (0600, ignoré par git),
que `scripts/ensure-local-secrets.sh` (appelé par `scripts/decrypt-secrets.sh`) relit à chaque fois :

| Clé | Comportement |
|---|---|
| `FACE_INTERNAL_TOKEN`, `FACE_DATA_KEY`, `BACKOFFICE_BOOTSTRAP_TOKEN` | générés **une fois** dans `.env.local` s'ils manquent dans SOPS, puis recopiés dans `.env`. Si SOPS les fournit, **SOPS l'emporte** ; une valeur différente dans `.env.local` déclenche un avertissement sur stderr (nom de la clé seulement, jamais la valeur) — pour `FACE_DATA_KEY`, les enrôlements chiffrés avec l'autre clé deviendraient illisibles. |
| `MQTT_BIND_ADDR` | **jamais généré**. S'il est présent dans `.env.local`, il **remplace** la valeur de SOPS dans `.env` (c'est une surcharge de poste). |

**Machine sans le hotspot** (pas d'IP `192.168.137.1`, `mosquitto` échoue avec `cannot assign requested
address`, y compris via `make up-full` qui lève le profil `iot`) :

```bash
echo 'MQTT_BIND_ADDR=127.0.0.1' >> .env.local   # durable : survit à `make decrypt`
# ou, ponctuellement (l'environnement du shell prime sur --env-file) :
MQTT_BIND_ADDR=127.0.0.1 make up-full
```

## Garde-fous

- `.gitignore` bloque `.env`, `*.age`, `keys.txt`.
- `gitleaks` en pre-commit (voir `security/hardening/`) empêche un secret en clair d'être commité.
- `security/hardening/audit.sh` vérifie l'absence de secret en clair avant packaging.
- **Jamais** committer `secrets.enc.env` en version déchiffrée, ni la clé privée.

## Vault (option)

HashiCorp Vault en mode dev reste une alternative acceptée par le sujet. SOPS est retenu par défaut pour sa simplicité sur 16 Go de RAM et son intégration git naturelle.
