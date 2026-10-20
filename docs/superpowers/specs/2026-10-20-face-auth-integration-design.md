# Design — Intégration de la reconnaissance faciale dans l'auth du back-office

- **Date :** 2026-10-20 · **Branche :** `feat/face-auth-integration` (depuis `origin/main` @ `472cb13`)
- **Source :** Consigne Additionnelle 1 (`docs/sujet/consigne additionnelle.pdf`, commit `9b96997`) ; modèle de l'équipe `ValentinFurcy/face_recognition` (`face_recognition.ipynb`).
- **Base existante (Yanis, L0–L3) :** `services/face-id` (backend stub), auth à étapes `identify → face → password` + verrouillage, `services/backoffice` (login sobre), firmware `iot/esp8266-led`, config `infra/mosquitto`. Cadrage : [`docs/consigne-additionnelle-1.md`](../../consigne-additionnelle-1.md).

## 1. Objectif

Terminer l'intégration de bout en bout : brancher **le vrai modèle de l'équipe** (avec sa vérification de vivacité par poses), ajouter **l'inscription avec prise de photos** et la **gestion des habilitations**, **piloter réellement l'ESP8266** via MQTT, câbler l'infra, et donner à **l'étape de reconnaissance faciale** une mise en scène sci-fi marquante.

## 2. Périmètre

**Dans le périmètre :** `services/face-id`, `services/auth` (étapes, admin, bootstrap, MQTT), `services/backoffice` (login + habilitations), `libs/python/resilience_db` (migration), `infra/compose`, `infra/mosquitto`, `security/waf`, `security/sops`, docs (contrat §5, cadrage, ADR, README/CDC, roadmap).

**Hors périmètre (ne pas toucher) :** `dashboard/`, `services/front`, la boucle ZTR (`verify_tx`, détection, remédiation), le firmware (sauf correctif nécessaire), `POST /api/v1/login`.

**Style visuel :** le back-office reste **fidèle au thème du front** (tokens `page/frame/line/ink/night/ok/ko/warn`, Instrument Sans + JetBrains Mono, champs `field`, `btn-primary`, login en deux panneaux nuit/blanc). Le **traitement sci-fi est réservé à l'étape de reconnaissance faciale** (composant `FaceScanner`, au login comme à l'enrôlement).

## 3. Décisions

| # | Décision | Pourquoi |
|---|---|---|
| D1 | App cible = `services/backoffice` (ADR 0004 inchangée) | Login à étapes déjà là ; front client et ZTR intacts |
| D2 | Caméra lue par `getUserMedia` (ADR 0005 conservée) **+ listener WAF réservé à l'hôte** : `127.0.0.1:9443` sert le back-office **et** `/api/v1/auth/*` + `/api/v1/admin/*` ; ces routes ne sont **pas** servies sur 80/443 | Seul un navigateur du PC Hôte peut joindre l'étape visage ⇒ la caméra est forcément celle de l'hôte (consigne). Pas d'agent Windows, pas de build dlib sous Windows |
| D3 | Modèle = `face_recognition`/dlib de l'équipe (128-d, distance euclidienne, seuil 0.6), backend `team` de `face-id` | Modèle livré et validé par l'équipe |
| D4 | **Vivacité par poses** (notebook) : enrôlement = 3 poses (face, profil gauche, profil droit) ; login = mêmes 3 poses dans un **ordre aléatoire tiré par le serveur** à chaque `identify`. Match ssi les 3 poses sont correctes et chacune ≤ seuil vs la pose enrôlée | Ferme le risque résiduel « photo/vidéo rejouée » du cadrage §7 |
| D5 | Stockage : 3 embeddings **et** 3 photos (vignettes JPEG ~240 px), **chiffrés AES-256-GCM** au repos (clé `FACE_DATA_KEY`, SOPS ; AAD = username). Effacement = suppression complète | Choix produit (affichage admin, ré-enrôlement) ; **amende** la règle « jamais d'image » du cadrage → contrat + RGPD mis à jour, ADR 0007 |
| D6 | LED : `MqttLedNotifier` (paho-mqtt, QoS 1, fail-open) remplace `LogLedNotifier` ; `auth` lit aussi `resilience/led/status` (LWT) pour afficher l'état du module | Termine L5-2 ; états sémantiques inchangés (ADR 0006) |
| D7 | Délais imposés **côté serveur** par poste (`client_ip`) : visage refusé ⇒ `identify` refusé **30 s** (LED rouge fixe 30 s, caméra éteinte à la fin) ; mot de passe refusé ⇒ **3 s** (rouge ×10 = 10 × 300 ms) | Lecture littérale de la consigne ; l'UI affiche un compte à rebours synchronisé |
| D8 | Verrouillage existant conservé : 2 échecs ⇒ 5 min par `(username, ip)` | Déjà conforme (CA4) |
| D9 | Premier admin : écran **Initialisation** si aucun admin n'est enrôlé, protégé par `BACKOFFICE_BOOTSTRAP_TOKEN` (SOPS), désactivé dès qu'un admin enrôlé existe | Résout l'œuf et la poule de l'enrôlement |
| D10 | Pose détectée **dans le navigateur** (MediaPipe Face Landmarker, auto-hébergé) uniquement pour l'UX : maillage, guidage, capture auto après 1 s stable. **Le serveur revalide** pose + identité | 30 fps fluides ; aucune décision côté client |

## 4. Composants

### 4.1 `face-id`

- **Interface `Recognizer` v2 :** `analyze(image) -> FaceSample{embedding, pose, faces}` (lève `NoFaceError`), `distance(a, b) -> float`, `threshold` (distance max), `model_version`. Le calcul de pose (`rotation` nez/mâchoire, seuils 0.10 / 0.15) est repris du notebook dans un module pur `poses.py`.
- **Backends :** `team` (face_recognition, `num_jitters=5` à l'enrôlement, 1 au login) ; `stub` (déterministe : les octets encodent `pose|identité`, pour les tests) ; `insightface` conservé (pose estimée depuis les 5 keypoints).
- **`POST /api/v1/enroll`** (token) : `{username, enrolled_by, poses:{face, gauche, droite: b64}}`. Pour chaque pose : un seul visage et la bonne pose ; puis cohérence (profils ≤ seuil vs face). Une pose KO ⇒ **toute la série est refusée** : `422 {error:{code:"enrollment_rejected", details:[{pose, reason}]}}` avec `reason ∈ no_face | multiple_faces | wrong_pose | inconsistent`. OK ⇒ stockage chiffré.
- **`POST /api/v1/verify`** (token) : `{username, frames:[{pose, image_b64}]×3}` ⇒ `{match, model_version}`. Le motif d'échec reste dans les logs uniquement (pas d'oracle).
- **`GET /api/v1/enrollments/{username}/photos`** (token) ⇒ vignettes déchiffrées pour l'admin, journal `face_photos_viewed`.
- **`DELETE /enroll/{username}`** et **`GET /enrollments`** inchangés (aucune biométrie dans la liste).
- **Chiffrement :** `crypto.py` (AES-GCM, nonce 96 bits, format versionné `v1|nonce|ct`). `/ready` échoue si la clé est absente ou invalide.

### 4.2 `resilience_db` — migration `0003`

`face_enrollments` : `embedding` contient désormais le **blob chiffré** des 3 gabarits par pose ; ajout de `photos` (LargeBinary, nullable, chiffré) et `poses` (str, ex. `face,gauche,droite`). Les enrôlements v1 (stub, non chiffrés) sont **invalidés** : réenrôlement requis, détecté via `model_version`.

### 4.3 `auth`

- **`identify`** ⇒ ajoute `poses: ["droite","face","gauche"]` (permutation `secrets.SystemRandom`), mémorisée dans le challenge. Si le poste est en refroidissement : `429 {code:"cooldown"}` + `Retry-After`.
- **`face`** ⇒ `{challenge_id, frames:[{pose, image_b64}]}`, avec l'**ordre des frames = ordre du challenge** (sinon échec). Relai vers face-id. Plafond : 3 × 600 Ko.
- **MQTT :** `MqttLedNotifier` (`connect_async` + `loop_start`, reconnexion auto, publication non bloquante, compteur `resilience_led_publish_total`) ; abonnement `status` ⇒ `GET /api/v1/auth/device` ⇒ `{led_online: bool | null}`.
- **Admin** (`Authorization: Bearer`, rôle `admin`) :
  - `GET /api/v1/admin/users` ⇒ `[{username, role, enrolled, enrolled_at, enrolled_by}]`
  - `POST /api/v1/admin/users` ⇒ `{username, password, role}` → `201` (sans compte bancaire)
  - `PATCH /api/v1/admin/users/{u}` ⇒ `{role}`
  - `PUT /api/v1/admin/users/{u}/face` ⇒ `{poses}` → relai `enroll` avec `enrolled_by = sub`
  - `DELETE /api/v1/admin/users/{u}/face`
  - `GET /api/v1/admin/users/{u}/face/photos`
  - Garde-fou : on ne peut ni rétrograder ni désenrôler **le dernier admin enrôlé**.
- **Bootstrap :** `GET /api/v1/auth/bootstrap` ⇒ `{required}` ; `POST` ⇒ `{token, username, password, poses}`, crée ou met à jour un admin et l'enrôle. Comparaison en temps constant, rate-limité, refus si non requis.
- **Événements ajoutés au contrat :** `admin_user_created`, `admin_role_changed`, `admin_face_enrolled`, `admin_face_revoked`, `backoffice_bootstrap`, `face_photos_viewed`, `auth_cooldown`.

### 4.4 `backoffice`

- **Thème :** reprise des tokens et polices du front (`index.css`, fontsource) ; `Brand` identique ; login en deux panneaux comme le front.
- **`LoginPage` :** identifiant ⇒ `FaceScanner` (mode `verify`, ordre des poses du serveur) ⇒ mot de passe ⇒ accueil. Compte à rebours de refroidissement (30 s / 3 s) et de blocage (5 min) ; jumeau LED (`LedIndicator`) aux mêmes timings que le firmware ; pastille « Module LED en ligne / hors ligne ».
- **`FaceScanner` (sci-fi, seul écran stylé) :**
  - panneau `night` : vidéo miroir, canvas superposé avec le maillage MediaPipe, réticule à coins, ligne de balayage, grille fine, coordonnées et télémétrie en mono ;
  - consigne de pose avec flèche animée ; anneau de maintien sur 1 s ; flash de capture ; puces d'étape `1/3 · 2/3 · 3/3` ;
  - phase « ANALYSE » avec anneaux concentriques ; verdict vert « IDENTITÉ CONFIRMÉE » ou rouge « NON RECONNU » (glitch bref) ;
  - `prefers-reduced-motion` respecté.
  - **Repli** si MediaPipe ne se charge pas : bouton « Capturer » par pose avec compte à rebours 3-2-1.
- **`HabilitationsPage`** (admin, style front) : tableau des agents, changement de rôle, voir les photos, révoquer, ré-enrôler ; assistant **« Nouvel agent »** (identité, mot de passe, rôle → `FaceScanner` en mode `enroll`, ordre fixe, vignettes → validation, avec les erreurs serveur par pose).
- **`BootstrapPage`** : même assistant + token.
- **MediaPipe :** `@mediapipe/tasks-vision` ; wasm copié depuis `node_modules`, modèle `face_landmarker.task` téléchargé à l'install/build (URL + sha256 épinglés) ; CSP du back-office : `script-src 'self' 'wasm-unsafe-eval'`.

### 4.5 Infra et sécurité

- **compose :**
  - `face-id` (réseaux `app`, `data`, durci, `read_only`) ;
  - `backoffice` (`app`) ;
  - `mosquitto` (image épinglée, `ports: "${MQTT_BIND:-192.168.137.1}:1883:1883"`, passwd généré au démarrage depuis l'env SOPS, durci) ;
  - env `auth` et `face-id` complétées ;
  - WAF : `ports` + `"127.0.0.1:9443:9443"`.
- **WAF :** nouveau `server { listen 9443 ssl; }` ⇒ `/` → backoffice, `/api/v1/auth/` et `/api/v1/admin/` → auth, `client_max_body_size 4m`. Le serveur public renvoie 404 sur ces préfixes.
- **mosquitto `aclfile` :** `auth` obtient `read resilience/led/status`.
- **SOPS `secrets.example.env` :** `FACE_INTERNAL_TOKEN`, `FACE_DATA_KEY`, `MQTT_AUTH_PASSWORD`, `MQTT_LED_PASSWORD`, `BACKOFFICE_BOOTSTRAP_TOKEN`.
- **`face-id` Dockerfile :** dlib compilé dans l'étage builder (cmake + build-essential), runtime slim non-root ; modèles `face_recognition_models` inclus.

## 5. Flux

**Login.**
1. `identify(u)` renvoie `{challenge_id, poses}`, LED `idle`, caméra ON.
2. `FaceScanner` capture les 3 poses dans l'ordre demandé.
3. `face` relaie à face-id `verify`.
   - Match : LED `recognized` (vert clignotant), caméra OFF, étape mot de passe.
   - Pas de match : LED `not_recognized` (rouge fixe 30 s) ; caméra éteinte à 30 s ; identifiant vidé ; refroidissement 30 s ; 1 reprise puis blocage 5 min.
4. `password` :
   - OK : LED `auth_ok` (vert fixe 30 s) ; séquence « ACCÈS AUTORISÉ » puis accueil.
   - KO : LED `auth_fail` (rouge ×10) ; refroidissement 3 s ; retour à l'identification.

**Inscription d'un agent.** L'admin connecté ouvre « Nouvel agent » : identité, puis capture face → gauche → droite, puis `POST users` + `PUT face`. Le serveur valide la série (refus ⇒ reprendre les 3 poses), puis chiffre et stocke.

## 6. Erreurs et mode dégradé

- face-id injoignable ⇒ `503 face_service_unavailable` (le back-office est inaccessible par conception, break-glass documenté).
- Broker absent ⇒ l'auth continue, `led_publish_failed`.
- Caméra refusée ⇒ retour à l'identifiant avec un message.
- MediaPipe absent ⇒ capture manuelle.
- `BACKOFFICE_FACE_REQUIRED=false` conservé pour les répétitions.

## 7. Tests

- **face-id :** stub poses (enrôlement OK, pose fausse, multi-visages, incohérence), verify (ordre, pose fausse, identité fausse, non enrôlé ≡ no-match), chiffrement (blob ≠ clair, mauvaise clé ⇒ erreur, AAD), photos (token requis, audit), `poses.py` (rotation/seuils), contrat `Recognizer` v2.
- **auth :** poses aléatoires présentes et permutées, frames dans le désordre ⇒ échec, refroidissements 30 s / 3 s, MQTT (faux client : payloads, QoS, fail-open, statut LWT), admin (RBAC 401/403, CRUD, garde du dernier admin), bootstrap (token, désactivation). Non-régression des 50 tests existants mis à jour.
- **backoffice (Vitest) :** login complet avec détecteur de pose et caméra mockés, refroidissement, blocage, verdicts, assistant d'enrôlement (erreurs par pose), RBAC de l'UI, repli manuel.
- **Hors stack :** modèle réel, caméra, broker et ESP sont validés en recette sur le PC Hôte (checklist dans le README backoffice).

## 8. Docs

- Contrat §5 (API v2, événements, D5) ; cadrage §5–§7 ; **ADR 0007** (listener hôte + vivacité par poses + photos chiffrées) ;
- CDC/README de face-id, auth, backoffice, mosquitto ; `secrets.example.env` ;
- roadmap consigne (L1, L3-4, L5, L6, L7) et `ROADMAP.md`.
