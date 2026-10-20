# Cadrage — Consigne Additionnelle 1 : renforcement de l'authentification du back-office

**Source :** *Workshop 2026-27 / M2 — Consigne Additionnelle 1* (EPSI). Deux pages scannées, reçues le 2026-10-20.
**Périmètre :** PC Hôte uniquement (celui qui délivre le PA `RESILIENCE-G1` et héberge la stack Docker). Données toujours fictives, Blue Team, périmètre offensif inchangé.
**Statut :** cadrage figé — **backlog & suivi dans [`consigne-additionnelle-1-roadmap.md`](consigne-additionnelle-1-roadmap.md)**.

> Ce document est le **contrat de la consigne** : il reformule le besoin, trace chaque exigence vers un composant, acte les décisions d'architecture (ADR à créer), et spécifie le **delta** à appliquer à [`contracts.md`](contracts.md) (qui reste FIGÉ : la modification passe par la première tâche du backlog). Le `/avancer` et la skill `resilience-component` s'appliquent à chaque tâche.

---

## 1. Reformulation du besoin

Le back-office du SI possède déjà une page d'authentification **identifiant / mot de passe**. La consigne demande de la renforcer avec **un facteur biométrique** et **un indicateur physique** :

1. **Authentification à étapes (identifiant → visage → mot de passe).** Après la saisie de l'**identifiant**, une **caméra USB** (branchée **obligatoirement sur le PC Hôte**) s'active et une **IA légère de reconnaissance de visage** confirme que le visage correspond à l'identifiant. Si oui → la saisie du **mot de passe** est débloquée. Sinon → l'identifiant est remis à vide, la caméra s'éteint ; **1 seule reprise** autorisée, puis **blocage 5 minutes** (cycle répétable).
2. **Gestion des habilitations dans le back-office.** L'enrôlement des visages et la gestion complète des habilitations (qui a le droit, avec quel visage) sont intégrés au back-office.
3. **Objet connecté ESP8266 + LED bicolore (rouge/vert)**, connecté en **WiFi au PA de la solution**, piloté par l'état de la phase d'authentification (machine à états §5). IDE imposé : **JetBrains CLion + PlatformIO**.

Le tout tourne sur le **PC Hôte** : c'est lui qui porte la caméra, l'IA de reconnaissance, le back-office et le point d'accès auquel se connecte l'ESP8266.

---

## 2. Traçabilité exigence → composant

| # | Exigence de la consigne | Composant(s) | Type |
|---|---|---|---|
| **CA1** | Saisie identifiant **puis** activation caméra USB (étape dédiée, caméra sur le PC Hôte) | `services/backoffice` (webcam `getUserMedia` côté hôte) + `services/auth` (orchestration du challenge) | nouveau + modifié |
| **CA2** | IA légère de **reconnaissance de visage** (1:1, identifiant ↔ visage) | `services/face-id` (nouveau service) | nouveau |
| **CA3** | Visage reconnu ⇒ saisie mot de passe débloquée ; sinon identifiant vidé + caméra éteinte | `services/auth` (machine à états du challenge) + `services/backoffice` (UI) | modifié + nouveau |
| **CA4** | **1 reprise** puis **blocage 5 min** (et cycle répétable) | `services/auth` (verrouillage par `(username, ip)`) | modifié |
| **CA5** | **Gestion complète des habilitations** (enrôlement visage + rôles) dans le back-office | `services/backoffice` (UI admin) + `services/auth` (rôles) + `services/face-id` (enrôlement) + `resilience_db` (modèle) | nouveau + modifié |
| **CA6** | ESP8266 + **LED bicolore** piloté par la phase d'auth, **WiFi sur le PA** | `iot/esp8266-led` (firmware PlatformIO) | nouveau |
| **CA7** | **Machine à états LED** (off / vert clignotant / vert fixe 30 s / rouge ×10 / rouge fixe 30 s) — voir §5 | `iot/esp8266-led` (rendu) + `services/auth` (publication des états) | nouveau + modifié |
| **CA8** | Transport des états vers l'objet connecté (hôte ↔ ESP sur `192.168.137.0/24`) | `mosquitto` (broker MQTT) + client MQTT dans `services/auth` | nouveau + modifié |
| **CA-T** | Contrats, observabilité, sécurité/RGPD, gouvernance, tests, déploiement | `docs/contracts.md`, `infra/*`, `security/*`, `docs/ebios-rm.md`\|`pca-pra.md`\|`nis2-dora.md`, `tests/e2e` | modifié |

---

## 3. Décisions de cadrage (ADR à créer)

> À formaliser dans `docs/adr/0004…0006` (première tâche de chaque lot). Chaque décision liste l'alternative écartée.

### D1 — Le « back-office » = nouvelle app `services/backoffice`, pas le front client *(ADR 0004)*
Le `front` existant est l'**app client** de la banque fictive. La consigne vise un **back-office privilégié** (« gestion complète des habilitations »). **Décision :** créer une petite app React/Vite/TS/Tailwind `services/backoffice`, servie **derrière le WAF** sur une route/vhost dédiée, **gated par rôle** (`operator`/`admin`). Le backend (auth à étapes, face-id, LED) est **identique quel que soit l'hôte UI** : si l'équipe préfère greffer l'écran sur le `front` existant (option B), seul le lot L3 change, pas les autres.
*Alternative écartée :* durcir le login du `front` client — mélange accès client et accès privilégié, lisibilité jury moindre.

### D2 — La caméra USB est lue **dans le navigateur de l'hôte** (`getUserMedia`), pas montée dans Docker *(ADR 0005)*
Docker Desktop / WSL2 ne fait pas de passthrough USB fiable pour une webcam. Le back-office est **ouvert sur le PC Hôte** : `navigator.mediaDevices.getUserMedia()` accède donc à la **caméra USB de l'hôte**, satisfait l'exigence « caméra sur le PC Hôte », et envoie les **trames (JPEG base64)** au service `face-id` conteneurisé. La caméra n'est **active que pendant l'étape d'identification** et **éteinte** sitôt la phase terminée (exigence consigne + vie privée).
*Alternative écartée :* agent de capture côté hôte (hors Docker) poussant vers face-id — composant Windows supplémentaire à maintenir, sans gain ici.

### D3 — Pilotage LED via **MQTT (Mosquitto)**, auth publie des **états sémantiques**, le firmware rend les motifs *(ADR 0006)*
L'ESP est sur le hotspot `192.168.137.0/24` ; les conteneurs sont sur des réseaux Docker internes. Il faut **un point de rencontre réseau**. **Décision :** un broker **Mosquitto** durci, **bindé sur l'interface hotspot** (comme le WAF est le seul ingress HTTP, le broker est le seul ingress MQTT), authentifié (creds SOPS) + **ACL par topic**. `auth` **publie des états sémantiques** (`idle|recognized|auth_ok|auth_fail|not_recognized`) ; le **firmware** mappe chaque état vers son **motif + timing** (vert fixe 30 s, rouge ×10, etc.). La publication MQTT dans `auth` est **fail-open** : un broker injoignable n'empêche **jamais** la connexion (la LED est un indicateur, pas un facteur).
*Alternatives écartées :* ESP en serveur HTTP (auth doit connaître l'IP de l'ESP, franchissement de réseaux) ; service `led-bridge` dédié (sur-découpage pour un workshop — gardé comme option de montée en charge si l'équipe veut sortir MQTT du périmètre d'`auth`).

### D4 — La biométrie **renforce l'accès privilégié uniquement**, le reste du SI est inchangé *(cf. §8 résilience)*
Le facteur visage + LED s'applique **au back-office** (accès privilégié), **exactement comme le demande la consigne** (« renforcer l'authentification du **back-office** »). Le `POST /login` classique reste la voie des **comptes de service** (`verify_tx`, `seed`) et du front client. **Conséquence capitale :** la boucle Zero-Touch Recovery (détection → remédiation → `verify_tx`) **ne dépend jamais** du visage, de la caméra, du broker ni de l'ESP. Aucun risque d'auto-DoS de la démo notée.

---

## 4. Architecture cible

```
┌───────────────────────── PC HÔTE (192.168.137.1, PA RESILIENCE-G1) ──────────────────────────┐
│                                                                                               │
│  Navigateur hôte ──webcam USB (getUserMedia)──┐                                               │
│     (back-office, route /admin)               │ trames JPEG b64                               │
│                                               ▼                                               │
│  edge:  WAF ──────────────► backoffice (react) ──► auth ──1:1 verify──► face-id ──► postgres  │
│                                                     │  (app)              (app+data)  (data)   │
│                                                     │ publie états LED (fail-open)             │
│                                                     ▼                                          │
│  hotspot-iface:  mosquitto (broker MQTT, auth + ACL topic) ◄── subscribe ── ESP8266 (WiFi)    │
│                                                                              └─ LED bicolore   │
│                                                                                               │
│  Inchangé : front client, payment-api, detector, remediation, verify_tx, observabilité…       │
└───────────────────────────────────────────────────────────────────────────────────────────────┘
```

**Composants nouveaux :** `services/face-id`, `services/backoffice`, `iot/esp8266-led`, broker `mosquitto`.
**Composants modifiés :** `services/auth` (challenge à étapes, verrouillage, rôles, publication LED), `resilience_db` (table `face_enrollments` + colonne `role`), `infra/compose` + `infra/prometheus` + `security/*` + `docs/*`.

---

## 5. Machines à états (source de vérité pour l'implémentation)

### 5.1 Challenge d'authentification (`services/auth`)

| État | Entrée | Transition | LED émise |
|---|---|---|---|
| `IDENTIFY` | identifiant saisi → `POST /auth/identify` | crée un `challenge_id`, caméra ON, step=`face` | `idle` (off) |
| `FACE` | trame → `POST /auth/face` | `face-id` match → `PASSWORD` ; no-match → `IDENTIFY` (identifiant vidé, caméra OFF) | match → `recognized` ; no-match → `not_recognized` |
| `PASSWORD` | mot de passe → `POST /auth/password` | bon → `OK` (JWT émis, rôle vérifié) ; mauvais → `IDENTIFY` (tout recommence) | OK → `auth_ok` ; KO → `auth_fail` |
| `OK` | — | session ouverte, back-office disponible | `auth_ok` (vert fixe 30 s puis off) |
| `LOCKED` | 2ᵉ échec d'accès dans le cycle | blocage **5 min** par `(username, source_ip)` ; `429 Retry-After` | `idle` |

- **Anti-énumération :** un identifiant **inconnu** n'a **pas d'enrôlement** ⇒ `no-match`, donc chemin **identique** à « visage non reconnu ». `POST /auth/identify` renvoie **toujours** un `challenge_id` (ne révèle pas l'existence du compte).
- **Verrouillage (CA4) :** compteur unifié d'**échecs d'accès** = `face no-match` **ou** `mot de passe erroné`. Seuil par défaut **2** (⇒ « 1 reprise »), puis **5 min**. Configurable (`BACKOFFICE_MAX_ATTEMPTS`, `BACKOFFICE_LOCKOUT_SECONDS`). Lecture littérale de la consigne (phase identification) documentée ; l'unification couvre aussi le brute-force mot de passe.
- **Rejeu :** le `challenge_id` est **à usage unique par étape** (retiré atomiquement), TTL court (`BACKOFFICE_CHALLENGE_TTL`, défaut 60 s) — il ne peut être rejoué. La trame elle-même n'étant pas liée au challenge, une photo volée reste un risque (spoofing/liveness, §7).
- **Store :** en mémoire, par processus (cohérent avec le rate-limit auth existant — limite assumée §10 ; option Redis documentée).

### 5.2 LED bicolore (`iot/esp8266-led`) — rendu des états (CA7)

| État reçu (MQTT) | Motif LED | Durée | Puis |
|---|---|---|---|
| `idle` | éteinte | — | — |
| `recognized` | **vert clignotant** | jusqu'à l'état suivant | attend `auth_ok`/`auth_fail` |
| `auth_ok` | **vert fixe** | **30 s** | éteinte |
| `auth_fail` | **rouge clignotant ×10** | 10 cycles | éteinte → la phase identification recommence |
| `not_recognized` | **rouge fixe** | **30 s** | éteinte → caméra OFF → ré-saisie identifiant |

- **Défaut = éteinte.** Le firmware est **non bloquant** (`millis()`, aucun `delay()` dans la `loop`). Les timings (30 s, ×10) sont **portés par le firmware** : le contrat réseau reste minimal (un état sémantique).
- **LWT (last will)** MQTT → l'ESP publie son indisponibilité ; l'hôte sait si l'objet est hors ligne (observabilité).

---

## 6. Delta à appliquer à `contracts.md` (FIGÉ → via la tâche L0-1)

### 6.1 Nouveaux `event` réservés (§1) — à ajouter à `RESERVED_EVENTS`
`auth` : `auth_identify_started`, `auth_face_recognized`, `auth_face_rejected`, `auth_locked_out`, `led_state_published`, `led_publish_failed`.
`face-id` : `face_verify_match`, `face_verify_nomatch`, `face_verify_error`, `face_enrolled`, `face_enrollment_revoked`.
*(Jamais la trame, jamais l'embedding, jamais le mot de passe dans un log.)*

### 6.2 Nouvelles métriques (§2, préfixe `resilience_`)
| Métrique | Type | Labels | Service |
|---|---|---|---|
| `resilience_face_verifications_total` | counter | `result` (`match`\|`nomatch`\|`error`) | face-id |
| `resilience_face_verify_duration_seconds` | histogram | — | face-id |
| `resilience_face_enrollments` | gauge | — | face-id |
| `resilience_auth_face_steps_total` | counter | `result` (`recognized`\|`rejected`) | auth |
| `resilience_auth_lockouts_total` | counter | — | auth |
| `resilience_led_publish_total` | counter | `state`, `result` (`ok`\|`error`) | auth |

### 6.3 API `face-id` (interne, jamais sur `edge`)
- `POST /api/v1/verify` — `{username, image_b64}` → `{match: bool, score: float, threshold: float, model_version: str}`. Appelé **uniquement par `auth`** (réseau `app`).
- `POST /api/v1/enroll` — en-tête `X-Internal-Token` — `{username, images_b64: [...]}` → `{enrolled: bool, quality: float, model_version}`. Stocke **l'embedding seul**.
- `DELETE /api/v1/enroll/{username}` — `X-Internal-Token` → `204`.
- `GET /api/v1/enrollments` — `X-Internal-Token` → `[{username, enrolled_at, enrolled_by, model_version}]` — **aucune donnée biométrique renvoyée**.
- `GET /health` · `GET /ready` (modèle chargé + DB) · `GET /metrics`.

### 6.4 API d'authentification à étapes (`auth`, consommée par le back-office)
- `POST /api/v1/auth/identify` — `{username}` → `200 {challenge_id, step:"face", expires_in, camera:true}` ; `429 {retry_after}` si `LOCKED`. **Toujours 200** hors lockout (anti-énumération).
- `POST /api/v1/auth/face` — `{challenge_id, image_b64}` → `200 {recognized, step:"password"|"identify", attempts_left}`.
- `POST /api/v1/auth/password` — `{challenge_id, password}` → `200 {access_token, token_type, expires_in, role}` (si rôle privilégié) ; `401 {step:"identify"}` sinon.
- `POST /api/v1/login` **conservé** pour comptes de service et front client (D4).

### 6.5 Protocole LED (MQTT)
- Broker : `mosquitto`, topics `resilience/led/cmd` (hôte→ESP, états §5.2), `resilience/led/status` (ESP→hôte, heartbeat + LWT). QoS 1.
- Payload `cmd` : `{"state":"idle|recognized|auth_ok|auth_fail|not_recognized","ts":"<iso8601>","challenge_id":"<uuid|null>"}`.
- Auth MQTT : user/mot de passe via SOPS ; **ACL** : `auth` publie `cmd` seul, l'ESP souscrit `cmd` + publie `status` seul ; `allow_anonymous false`.

### 6.6 Modèle de données (`resilience_db`)
- `users.role` : `customer` (défaut) \| `operator` \| `admin`. Le back-office exige `operator`/`admin`.
- Table `face_enrollments` : `user_id` (FK `users.id`, unique), `embedding` (BYTEA, **vecteur uniquement**), `model_version` (str), `enrolled_by` (str), `enrolled_at` (timestamptz). Migration Alembic dédiée.

---

## 7. Sécurité (points sondés par le jury)

- **Donnée biométrique = sensible (RGPD).** On stocke **l'embedding** (vecteur), **jamais** l'image. Table sur réseau `data` interne, accès via `X-Internal-Token`, renvoi d'enrôlements **sans biométrie**. **Chiffrement au repos** de la colonne `embedding` recommandé (clé SOPS) — a minima porté en risque résiduel. Droit à l'effacement : `DELETE /enroll/{username}`.
- **Le visage n'est pas un bypass.** C'est un **facteur ajouté** : l'étape mot de passe + le **rôle privilégié** restent obligatoires. Un visage reconnu seul n'ouvre rien.
- **Anti-spoofing / liveness.** Non exigé par la consigne mais **photo-d'une-photo** = angle d'attaque. Porté en **risque résiduel** + amélioration optionnelle (challenge de vivacité : clignement / mouvement). À documenter EBIOS.
- **Rejeu & fraîcheur :** le `challenge_id` est à **usage unique par étape** (retiré atomiquement), TTL court — il ne peut être rejoué. En revanche, la **trame** n'étant pas liée au challenge, une photo/trame volée reste utilisable sur un nouveau challenge : c'est le **risque de spoofing** ci-dessous (absence de liveness), porté en risque résiduel EBIOS. Option : nonce/horodatage lié à la trame.
- **Caméra :** active **uniquement** pendant l'étape identification, éteinte ensuite (consigne + vie privée).
- **Broker MQTT = nouvelle surface.** Durci comme le WAF : `allow_anonymous false`, creds SOPS, **ACL par topic**, bind **sur l'interface hotspot seulement**, TLS (`8883`) optionnel documenté, conteneur durci (non-root, `cap_drop`, `read_only`, healthcheck). L'ESP valide la LWT.
- **Anti-DoS d'accès légitime :** verrouillage **par `(username, ip)`** pour qu'un attaquant ne verrouille pas globalement un admin ; `/login` de service hors de ce chemin (D4).
- **Secrets :** `MQTT_USERNAME/PASSWORD`, `FACE_INTERNAL_TOKEN`, éventuelle clé de chiffrement embedding → **SOPS**, jamais commités ; `gitleaks` couvre. Firmware : `secrets.h` depuis template, **gitignored** (SSID/PSK du PA, creds MQTT).
- **Signal de détection (option) :** une rafale de `auth_face_rejected` / `face_verify_nomatch` est un indice d'attaque — brancher sur la fonction SOC (règle Loki) ou une feature ML (hors vecteur figé : à discuter). Porté en opportunité, pas en exigence.

---

## 8. Résilience & mode dégradé (cohérence avec le cœur du projet)

Ajouter un facteur biométrique dans un **chemin de connexion** crée un risque d'**auto-DoS** — contraire à la thèse Zero-Touch Recovery. Garde-fous :

1. **La boucle ZTR est indépendante** du visage/caméra/broker/ESP (D4). `verify_tx`, `seed`, détection et remédiation passent par `/login` de service. **Aucun** livrable noté (Axe 1, Clip Chrono) ne dépend de la caméra.
2. **MQTT fail-open :** broker ou ESP injoignables ⇒ l'authentification continue (la LED n'est qu'un témoin). Événement `led_publish_failed` journalisé.
3. **Indisponibilité du facteur visage :** si `face-id` est `down`, le back-office est inaccessible **par conception** (c'est un durcissement). Prévoir une **procédure break-glass** documentée (compte de service + `/login` + rôle, hors caméra) pour l'exploitation, tracée (PCA/PRA). Mode d'application **configurable** (`BACKOFFICE_FACE_REQUIRED`) pour les répétitions de démo.
4. **PCA/PRA :** nouveau scénario « perte du facteur biométrique » (RTO court via break-glass), RPO biométrie = dernier enrôlement (réenrôlement possible).

---

## 9. Matériel & outillage

| Élément | Choix / note |
|---|---|
| **Caméra USB** | Branchée sur le PC Hôte ; lue par le navigateur (D2). UVC standard. |
| **IA reconnaissance** | « légère », CPU/WSL2. Recommandé : **InsightFace `buffalo_s` (ONNX Runtime CPU)** — embeddings 512-d, cosine ; repli **`face_recognition` (dlib, 128-d)** si l'install ONNX est pénible. Seuil calibré en recette. Modèle téléchargé au build (image épinglée, R5). |
| **ESP8266** | Carte type NodeMCU/Wemos D1. **LED bicolore** rouge/vert (2 GPIO + résistances, ou LED 2 broches). WiFi sur le PA. |
| **IDE firmware** | **JetBrains CLion + PlatformIO** (imposé). `platformio.ini` : env carte **+ env `native`** pour les tests unitaires de la machine à états (exécutables sur le poste de dev **sans matériel**). |
| **Poste de dev** | Sans Docker/pip (venv `uv` 3.12 dans le scratchpad, cf. mémoire projet) : tout ce qui est **testable hors stack** (logique challenge, state machine firmware `native`, parseurs) doit l'être ; le reste (modèle réel, caméra, ESP physique, broker live) est validé **en recette** sur le PC Hôte. |

---

## 10. Hors périmètre / limites assumées

- Store de challenge/lockout **en mémoire par processus** (comme le rate-limit actuel) — Redis = montée en charge documentée.
- **Pas de liveness** v1 (porté en risque résiduel + option).
- Reconnaissance **1:1** (vérification identifiant↔visage), **pas** d'identification 1:N.
- Un seul ESP8266 / une seule LED (poste d'accueil du back-office).
- Broker MQTT **en clair** acceptable en labo (TLS optionnel documenté), bindé hotspot seulement.
- Back-office = périmètre **habilitations + login durci** ; pas de refonte des écrans métier.

---

## 11. Critères d'acceptation globaux (Definition of Done de la consigne)

Chacun est couvert par au moins un test (cf. backlog pour le mapping fin).

| # | Critère | Preuve attendue |
|---|---|---|
| G1 | Saisie identifiant → caméra ON → étape visage, **avant** tout mot de passe | e2e back-office + test auth (ordre des étapes imposé) |
| G2 | Visage reconnu ⇒ mot de passe débloqué ; non reconnu ⇒ identifiant vidé + caméra OFF | test auth challenge + e2e (fake recognizer) |
| G3 | **1 reprise** puis **blocage 5 min** par `(username, ip)` | test auth lockout + anti-énumération |
| G4 | `face-id` : match/no-match sur embedding, **jamais** d'image stockée/renvoyée | tests face-id (stub déterministe) + contrôle « no biometric leak » |
| G5 | Habilitations : enrôlement/révocation + rôles, gated back-office | tests face-id enroll + vitest back-office + test rôle auth |
| G6 | LED : les **5 états** rendus conformément à §5.2 (timings inclus) | tests firmware `native` (machine à états) |
| G7 | Pilotage LED de bout en bout, **fail-open** si broker down | test auth publication MQTT (mock) + recette broker live |
| G8 | ESP connecté au **PA** en WiFi, LED éteinte par défaut | recette matérielle (checklist J-recette) |
| G9 | Contrats à jour (events ⊂ `RESERVED_EVENTS`, métriques, API, protocole LED) | tests de conformité contrat de chaque composant |
| G10 | **La boucle ZTR / `verify_tx` reste verte et indépendante** du visage | e2e ZTR inchangé rejoué vert |
| G11 | Observabilité : `face-id` scrapé, logs JSON, LED status visible | recette `make up-full` + dashboards |
| G12 | Gouvernance mise à jour (EBIOS biométrie, PCA/PRA break-glass, NIS2/DORA accès) | docs révisées |

---

## 12. Dépendances & séquencement (chemin critique)

```
L0 Contrats/ADR ─┬─► L1 face-id ──────┐
                 ├─► L2 auth étapes ◄──┘ (consomme face-id) ─┬─► L3 back-office (UI) ─┐
                 │                                           ├─► L8 sécurité/RGPD      ├─► L10 e2e + recette + démo
                 ├─► L6 habilitations (rôles+enrôlement) ◄───┘                        │
                 ├─► L5 transport MQTT (broker) ─► L4 firmware ESP8266 ────────────────┤
                 └─► L7 infra/observabilité ──────────────────────────────────────────┘
                     L9 gouvernance (en parallèle, se cale sur L1/L2/L8)
```

Le **chemin critique** passe par **L0 → L2 → L3 → L10**. `face-id` (L1), le firmware (L4) et le broker (L5) sont parallélisables une fois le contrat figé (L0). Détail, estimations et suivi : **[`consigne-additionnelle-1-roadmap.md`](consigne-additionnelle-1-roadmap.md)**.
