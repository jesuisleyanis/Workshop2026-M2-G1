# Roadmap — Consigne Additionnelle 1 (auth back-office : visage + LED)

> Backlog ordonné et **suivi d'avancement** de la [Consigne Additionnelle 1](consigne-additionnelle-1.md).
> **Definition of Done par ticket** (non négociable, cf. `CLAUDE.md`) : ① code conforme aux contrats · ② tests **verts** · ③ doc (CDC/README du composant + doc transverse si une interface bouge) · ④ cette ligne mise à jour (statut + preuve). La commande `/avancer` et la skill `resilience-component` outillent chaque ticket.
> Légende : ⬜ à faire · 🟨 en cours · ✅ fait · 🔴 bloqué · ⏭️ reporté. Effort : **S** < 0,5 j · **M** ~1 j · **L** > 1 j.

## Tableau de bord

```
L0  Cadrage & contrats     [##########] 100%  contrat §5 v2 + ADR 0004-0007 + migrations 0002/0003 — tests verts
L1  Service face-id        [#########.]  90%  v2 (3 poses, chiffrement AES-GCM, photos) — 93 tests verts ; recette : build Docker de dlib + modèle réel
L2  Auth à étapes          [##########] 100%  poses aléatoires, frames ordonnées, refroidissements 30 s / 3 s, verrouillage — 186 tests auth verts
L3  Back-office + webcam    [#########.]  90%  login v2 + FaceScanner + habilitations + bootstrap — 131 tests Vitest ; recette : caméra réelle, marges 0,07 / 0,22
L4  Firmware ESP8266        [######....]  60%  machine à états + tests native + firmware posés ; recette matérielle à faire
L5  Transport MQTT          [########..]  80%  broker durci (compose, ACL) + MqttLedNotifier fail-open + GET /auth/device — 30 tests ; recette : broker live + ESP
L6  Habilitations           [##########] 100%  rôles + API admin + enrôlement/révocation + garde last_admin + bootstrap — tests verts
L7  Infra & observabilité   [######....]  60%  compose + WAF 9443 + SOPS + scrape face-id (54 tests infra/WAF) ; reste Makefile (L7-4) et recette compose/Loki
L8  Sécurité & RGPD         [###.......]  30%  RGPD amendé + chiffrement testé (L8-2) ; reste revue sécurité du flux (L8-1) et audit.sh (L8-3)
L9  Gouvernance             [######....]  60%  EBIOS (annexe) + PCA/PRA §5.7 rédigés ; reste NIS2/DORA (L9-3)
L10 Recette & e2e           [..........]   0%   e2e + checklist matérielle (non faits)
```

**Chemin critique :** L0 ✅ → L2 ✅ → L3 🟨 (recette caméra) → **L10 (recette & e2e : prochaine étape, rien n'est fait)**.
**Intégration de bout en bout livrée** (2026-10-20, branche `feat/face-auth-integration`, `5c425c6..HEAD`) : modèle de l'équipe, vivacité par poses, photos chiffrées, habilitations, bootstrap, LED MQTT, listener hôte `127.0.0.1:9443`. **Tout est testé hors stack ; rien n'a été validé en recette** (caméra réelle, build Docker de dlib, ESP8266 physique, broker live) — voir « Intégration de bout en bout » plus bas.

---

## L0 — Cadrage & contrats *(débloque tout)*

| ID | Tâche | Composant | Dépend | Effort | Statut | Preuve attendue |
|---|---|---|---|---|---|---|
| L0-1 | Appliquer le **delta contrat** (§6 du cadrage) : events réservés, métriques, API face-id, API auth à étapes, protocole LED, modèle données | `docs/contracts.md`, `resilience_common/events.py` | — | M | ✅ | contrat §5 + 11 events ajoutés, `RESERVED_EVENTS` + métriques étendus ; `test_reserved_events_match_contract_table` vert |
| L0-2 | ADR **0004** (back-office = app dédiée), **0005** (caméra navigateur), **0006** (LED via MQTT) | `docs/adr/` | — | S | ✅ | `docs/adr/0004…0006` au format maison |
| L0-3 | Migration `resilience_db` : `users.role` + table `face_enrollments` (embedding BYTEA) | `libs/python/resilience_db` | L0-1 | M | ✅ | migration `0002` (batch SQLite/PG) + modèles ; 2 nouveaux tests `test_db` verts (rôle borné, 1 enrôlement/user) ; auth 36 + payment-api 65 non régressés |

## L1 — Service `face-id` (IA légère de reconnaissance)

| ID | Tâche | Composant | Dépend | Effort | Statut | Preuve attendue |
|---|---|---|---|---|---|---|
| L1-1 | Scaffold service (CDC + README + FastAPI + `resilience_common` logs/métriques + `/health` `/ready` `/metrics`) — skill `nouveau-composant` | `services/face-id` | L0-1 | M | ✅ | package `face_id` + CDC + README + health/ready/metrics ; suite verte |
| L1-2 | Abstraction `Recognizer` (embed + compare) avec **backend InsightFace `buffalo_s`** et **stub déterministe** injectable pour les tests | `services/face-id` | L1-1 | L | 🟨 | `Recognizer` **v2** (`analyze`/`distance`/`threshold`, `poses.py` du notebook) ; backends `team` (dlib), `insightface`, `stub` ; `test_poses.py`, `test_recognizer_contract.py` ; commits `64cad40`, `cb0240b`. **Reste : smoke du modèle réel `team` (dlib non installé sur le poste de dev) en recette** |
| L1-3 | `POST /verify` (1:1, `{username,image_b64}`→`{match,score,threshold,model_version}`) + events `face_verify_*` + métriques | `services/face-id` | L1-2, L0-3 | ✅ | `POST /verify` v2 : 3 frames/poses, `{match, model_version}`, pas de score ; `test_enroll_three_poses_then_verify_in_random_order_matches`, `test_verify_rejects_wrong_pose_in_sequence`, `test_verify_requires_exactly_three_distinct_poses` ; `cb0240b` |
| L1-4 | `POST /enroll`, `DELETE /enroll/{username}`, `GET /enrollments` (token interne) — **embedding seul**, **aucune image renvoyée** | `services/face-id` | L1-3 | ✅ | `POST /enroll` (3 poses, refus en bloc `enrollment_rejected`), photos chiffrées, `DELETE`, `GET /enrollments` sans biométrie ; `test_enroll_rejects_whole_series_with_per_pose_details`, `test_templates_and_photos_are_encrypted_at_rest`, `test_photos_endpoint_requires_token_and_logs_view`, `test_enrollments_list_exposes_no_biometric_data` ; `cb0240b` |
| L1-5 | Dockerfile durci (slim, non-root, modèle épinglé au build) + requirements épinglés | `services/face-id` | L1-4 | 🟨 | `Dockerfile` (dlib compilé dans l'étage builder, runtime slim non-root, `read_only`) + `requirements*.txt` ; `test_face_id_service` (infra) ; `cb0240b`, `be727ad`. **Reste : `docker build` réel (jamais lancé : Docker indisponible sur le poste de dev)** |

> **L1 — 93 tests verts** (`cd services/face-id && pytest -q -p no:cacheprovider`), + `resilience_db` 10 (migration `0003`, `2f34384`). Backends réels `team` (dlib) et `insightface` écrits mais **non exécutés hors stack** (dépendances non installées) : validation en recette.

## L2 — Authentification à étapes *(chemin critique)*

| ID | Tâche | Composant | Dépend | Effort | Statut | Preuve attendue |
|---|---|---|---|---|---|---|
| L2-1 | Store de challenge en mémoire (TTL, usage unique par étape) + machine à états §5.1 | `services/auth` | L0-1 | M | ✅ | `challenge.py` (ChallengeStore/LockoutStore, horloge injectable) ; tests cycle + expiration + rejeu refusé |
| L2-2 | `POST /auth/identify` (toujours 200 hors lockout, **anti-énumération**) + event + caméra ON | `services/auth` | L2-1 | S | ✅ | `test_identify_unknown_user_still_returns_a_challenge` |
| L2-3 | `POST /auth/face` → appelle `face-id /verify` ; match→PASSWORD, no-match→IDENTIFY + compteur | `services/auth` | L2-2, L1-3 | ✅ | `HttpFaceVerifier` + stub injectable ; transitions, rejeu, `auth_face_steps_total`, 503 si face-id down |
| L2-4 | `POST /auth/password` (valide seulement en step PASSWORD) → JWT + **contrôle de rôle** ; KO→IDENTIFY | `services/auth` | L2-3 | ✅ | rôle dans le JWT ; saut d'étape 409, rôle non privilégié 403, mauvais mdp 401 + LED auth_fail |
| L2-5 | **Verrouillage** (CA4) : 2 échecs/cycle → **5 min** par `(username, ip)` + `429 Retry-After` + event `auth_locked_out` | `services/auth` | L2-3 | ✅ | `test_lockout_after_one_retry_then_5_minutes` (+ reset au succès, déblocage après délai) |
| L2-6 | `/login` **conservé** pour comptes de service / front client (D4) + non-régression auth | `services/auth` | L2-1 | ✅ | `test_legacy_login_still_works` ; 36 tests auth d'origine toujours verts (49 au total) |

> **L2 (v2, intégration) :** `identify` renvoie un **ordre aléatoire de poses** ; `face` exige 3 frames dans cet ordre ; refroidissements 30 s (visage) / 3 s (mot de passe) ; `96ae104` — `test_identify_returns_random_permutation_of_three_poses`, `test_frames_out_of_order_are_rejected_without_calling_face_id`, `test_face_rejection_starts_30s_cooldown_on_identify`, `test_wrong_password_starts_3s_cooldown`. Suite auth complète : **186 verts**.
>
> **L2 (v1) — 13 tests verts** (`services/auth/tests/test_auth_stepped.py`) ; suite auth complète **49 verts** à l'époque. LED émise via un notifieur injectable (fail-open) — le backend MQTT réel est L5-2. Le contrôle de rôle anticipe L6-1.
>
> **Point de branchement du modèle de l'équipe** (lié à L1-2) : `face-id` isole le modèle derrière l'interface `Recognizer`. Gabarit `backends/team_backend.py` + backend `team` + **`services/face-id/INTEGRATION-ML.md`** (contrat `embed()` + test de conformité) : le modèle du coéquipier se branche sans toucher au reste.

## L3 — Back-office + capture webcam *(chemin critique)*

| ID | Tâche | Composant | Dépend | Effort | Statut | Preuve attendue |
|---|---|---|---|---|---|---|
| L3-1 | Scaffold app React/Vite/TS/Tailwind `services/backoffice` (CDC + README + client API auth) | `services/backoffice` | L0-2 | M | ✅ | Vite 8 + React 19 + Tailwind 4 + Vitest ; `api/auth.ts` (client §5.2) ; lint + build + typecheck OK |
| L3-2 | Page login à étapes : saisie identifiant → **`getUserMedia`** (caméra hôte) → envoi trame → saisie mdp conditionnelle | `services/backoffice` | L3-1, L2-4 | L | ✅ | `LoginPage` v2 + `FaceScanner` (HUD sci-fi, MediaPipe auto-hébergé, repli manuel) + `useCamera` ; vitest (caméra et détecteur **mockés**) : ordre des poses du serveur, vidage sur rejet, caméra OFF, refroidissements, blocage ; `37c176d`, `30be1d5`, `b0c8092`. **Reste : caméra réelle en recette** |
| L3-3 | Témoin d'état miroir de la LED + messages (reconnu / non reconnu / blocage 5 min) | `services/backoffice` | L3-2 | S | ✅ | `LedIndicator` + `lib/led.ts` (jumeau LED aux timings firmware : 30 s, ×10 en 3 s) + pastille « module LED en ligne / hors ligne » (`GET /auth/device`) ; vitest `led.test.ts`, `LoginPage.test.tsx` ; `b0c8092` |
| L3-4 | Écran **habilitations** (liste users/rôles, enrôlement par webcam, révocation) gated `admin` | `services/backoffice` | L3-2, L6-2 | L | ✅ | `HabilitationsPage` (tableau, rôles, photos, révocation, ré-enrôlement) + `EnrollWizard` « Nouvel agent » + `BootstrapPage` ; `HabilitationsPage.test.tsx`, `EnrollWizard.test.tsx`, `BootstrapPage.test.tsx`, `admin.test.ts` ; `ce30e9a` |
| L3-5 | Dockerfile durci + route WAF dédiée (`/admin` ou vhost), `read_only`+tmpfs (parité front) | `services/backoffice`, `security/waf` | L3-2 | M | 🟨 | Dockerfile nginx non-root 8080 + headers (`camera=(self)`, CSP `wasm-unsafe-eval`) ; **route WAF livrée** : listener `127.0.0.1:9443` → back-office (`test_host_listener_9443_routes_auth_admin_and_backoffice`) ; `be727ad`. **Reste : build de l'image et rendu réel derrière le WAF (recette)** |

> **L3 — 131 tests Vitest verts** (`npm test`), lint + `tsc` + `vite build` OK. Login à étapes v2 (ordre de poses imposé serveur, caméra coupée hors scan, miroir LED, refroidissements, blocage 5 min) + habilitations + bootstrap. **Marges de capture client 0,07 / 0,22** (vs seuils serveur 0,10 / 0,15) **à calibrer en recette** (`captureMargins.ts`).

## L4 — Firmware ESP8266 (LED bicolore)

| ID | Tâche | Composant | Dépend | Effort | Statut | Preuve attendue |
|---|---|---|---|---|---|---|
| L4-1 | Projet PlatformIO (CLion) : `platformio.ini` (env carte **+ env `native`**), CDC + README + câblage LED | `iot/esp8266-led` | L0-2 | M | ✅ | `platformio.ini` (nodemcuv2 + native) + CDC + README (câblage D1/D2) |
| L4-2 | **Machine à états LED** §5.2 non bloquante (`millis()`), découplée du transport | `iot/esp8266-led` | L4-1 | ✅ | `lib/led/led_controller.h` (pure) + `test/` Unity : 5 états, timings 30 s / ×10, défaut off, parseur. **`pio test -e native` à jouer sur la machine CLion** (pas de g++ sur le poste de cadrage) |
| L4-3 | WiFi (PA `RESILIENCE-G<n>`) + client MQTT (subscribe `cmd`, publish `status`/LWT), `secrets.h` depuis template **gitignored** | `iot/esp8266-led` | L4-2, L5-1 | 🟨 | `src/main.cpp` (ESP8266WiFi + PubSubClient + ArduinoJson, LWT) + `secrets.h.example` + `.gitignore` posés ; **recette live** (connexion + réception) à faire |
| L4-4 | Robustesse : reconnexion WiFi/MQTT, LED off au boot, heartbeat | `iot/esp8266-led` | L4-3 | 🟨 | reconnexion + LED off au boot + heartbeat codés ; **recette coupure/reprise** à faire |

## L5 — Transport MQTT

| ID | Tâche | Composant | Dépend | Effort | Statut | Preuve attendue |
|---|---|---|---|---|---|---|
| L5-1 | Broker **Mosquitto** durci : `allow_anonymous false`, user/mdp SOPS, **ACL par topic**, bind interface hotspot, image épinglée | `infra/compose`, `security/*` | L0-1 | 🟨 | Service Compose `mosquitto` (image épinglée `eclipse-mosquitto:2.0.20`, `${MQTT_BIND:-192.168.137.1}:1883`, passwd généré au démarrage depuis SOPS dans un tmpfs, durci, healthcheck), ACL (`auth` : write `cmd`, read `status` ; `led` : l'inverse) ; `test_mosquitto_not_published_on_all_interfaces`, `test_mosquitto_passwd_lives_in_tmpfs_run_dir_and_config_is_read_only`, `test_acl_auth_reads_led_status_and_least_privilege_kept` ; `be727ad`. **Reste : démarrage réel du broker (recette)** |
| L5-2 | Client MQTT dans `auth` : publie les états §5.2, **fail-open** (broker down ⇒ auth continue), events `led_*` | `services/auth` | L5-1, L2-3 | M | ✅ | `MqttLedNotifier` (paho, QoS 1, `connect_async`, reconnexion auto, **fail-open**), souscription `status` (LWT) → `GET /api/v1/auth/device` ; 30 tests `test_led_mqtt.py` dont `test_publish_swallows_client_exception`, `test_publish_when_disconnected_is_error`, `test_status_messages_update_online` ; `1c6ed48`. Broker live non joué |

## L6 — Habilitations (rôles + enrôlement)

| ID | Tâche | Composant | Dépend | Effort | Statut | Preuve attendue |
|---|---|---|---|---|---|---|
| L6-1 | Rôles (`customer`/`operator`/`admin`) exploités par auth (claim JWT + garde back-office) | `services/auth`, `resilience_db` | L0-3 | M | ✅ | Rôle dans le JWT + garde back-office (étape mot de passe `403 role_not_authorized`) + `require_admin` **revalidant le rôle en base** : `test_demoted_admin_with_still_valid_token_is_forbidden`, `test_invalid_expired_and_wrongly_signed_tokens_are_401` ; `02eb3ce` |
| L6-2 | Orchestration enrôlement : back-office → auth (token interne) → `face-id /enroll` ; traçabilité `enrolled_by` | `services/auth`, `services/face-id` | L6-1, L1-4 | M | ✅ | API admin (`/admin/users`, `PATCH` rôle, `PUT`/`DELETE` visage, photos) → `face-id /enroll` avec `enrolled_by = sub` ; garde **`last_admin`** : `test_enroll_face_relays_poses_and_actor`, `test_last_enrolled_admin_cannot_be_demoted`, `test_photos_returns_poses_and_logs_viewer` ; `02eb3ce`, `9db026a` |
| L6-3 | Seed : au moins un `admin` enrôlable pour la démo (visage de démo fictif documenté) | `scripts/`, `resilience_db` | L6-2 | S | ✅ | Remplacé par le **bootstrap** du premier admin (`BACKOFFICE_BOOTSTRAP_TOKEN`, actif tant qu'aucun admin enrôlé n'existe, refus d'un compte client) : `test_bootstrap_creates_enrolled_admin_then_not_required`, `test_bootstrap_denied_when_not_required`, `test_bootstrap_refuses_existing_customer_account`, rollback `test_bootstrap_failure_after_face_id_stored_revokes_and_deletes_new_user` ; `02eb3ce`, `9db026a`. `scripts/seed.py` **inchangé** (aucun compte admin pré-créé) |

## L7 — Infra & observabilité

| ID | Tâche | Composant | Dépend | Effort | Statut | Preuve attendue |
|---|---|---|---|---|---|---|
| L7-1 | Compose : `face-id`, `backoffice`, `mosquitto` (réseaux, profils, dépendances, durcissement, healthchecks) ; **WAF route `/api/v1/auth/*` → auth + vhost back-office (M-f)** ; réseau `app` interne (m9) | `infra/compose`, `security/waf` | L1-5, L3-5, L5-1 | M | 🟨 | Compose `face-id`, `backoffice`, `mosquitto`, env `auth`, WAF `127.0.0.1:9443` + 404 sur 80/443 pour `/api/v1/auth/` et `/api/v1/admin/`, plafonds ModSecurity 4 MiB : `test_new_services_are_hardened`, `test_host_listener_9443_is_published_on_loopback_only`, `test_public_server_returns_404_on_host_only_prefixes`, `test_modsecurity_body_limits_match_host_client_max_body_size` (54 tests infra + WAF) ; `be727ad`, `66f685d`. **Reste : `docker compose config/up`, `nginx -t` et prise en compte réelle de `MODSEC_REQ_BODY_*` par l'image (recette)** |
| L7-2 | Prometheus scrape `face-id` ; vérifier que Promtail capte les logs des nouveaux services | `infra/prometheus`, `infra/promtail` | L7-1 | S | 🟨 | Job Prometheus `face-id:8006` (`test_prometheus_scrapes_face_id`) ; `be727ad`. **Reste : cible UP et logs des nouveaux services dans Loki (recette `make up-full`)** |
| L7-3 | SOPS : `MQTT_*`, **`FACE_INTERNAL_TOKEN` (même valeur sur `auth` et `face-id`)**, (option) clé chiffrement embedding ; `secrets.example.env` + README | `security/sops` | L5-1 | S | ✅ | `secrets.example.env` : `FACE_INTERNAL_TOKEN`, `FACE_DATA_KEY`, `MQTT_AUTH_PASSWORD`, `MQTT_LED_PASSWORD`, `BACKOFFICE_BOOTSTRAP_TOKEN`, `MQTT_BIND` (valeurs factices) ; `test_sops_example_has_new_secrets_with_fake_values`, `test_auth_wired_to_face_id_and_mqtt` ; `be727ad` |
| L7-4 | Makefile/aliases : build modèle face-id, lancement broker ; `make test` agrège les nouveaux composants | `Makefile`, `README.md` | L7-1 | S | ⬜ | **Non fait** : `Makefile` `PY_COMPONENTS` ne contient pas `services/face-id` et `test-front` ne lance pas `services/backoffice` ⇒ `make test` ne couvre pas encore ces deux composants (lancer leurs suites à la main, cf. README de chaque composant) |

## L8 — Sécurité & RGPD

| ID | Tâche | Composant | Dépend | Effort | Statut | Preuve attendue |
|---|---|---|---|---|---|---|
| L8-1 | Revue `security-reviewer` du flux (surface MQTT/caméra, privilèges, pas de bypass visage, anti-énumération, fail-open) | tous | L2-5, L5-2, L3-5 | M | ⬜ | rapport de revue + correctifs |
| L8-2 | RGPD : embedding seul, (option) chiffrement au repos, effacement, rétention — tracé dans la doc | `services/face-id`, `docs/` | L1-4 | S | ✅ | RGPD **amendé** (ADR 0007, contrat §5.4, cadrage §7) : gabarits + vignettes ≤ 240 px **chiffrés AES-256-GCM** (`FACE_DATA_KEY`, AAD = username), consultation admin journalisée, effacement total ; `test_blob_est_chiffre_et_versionne`, `test_aad_differente_leve_seal_error`, `test_templates_and_photos_are_encrypted_at_rest`, `test_enrollments_list_exposes_no_biometric_data` ; `64cad40`, `cb0240b`. **L'amendement de la règle « jamais d'image » reste à valider par l'équipe (Yanis)** |
| L8-3 | Durcissement confirmé : `audit.sh` couvre face-id/backoffice/mosquitto (non-root, cap_drop, read_only, exposition) | `security/hardening` | L7-1 | S | ⬜ | `audit.sh` exit 0 |
| L8-4 | (Option) Signal SOC : règle Loki sur rafale `face_verify_nomatch`/`auth_face_rejected` | `infra/grafana\|loki` | L2-5 | S | ⏭️ | règle + test (si retenu) |

## L9 — Gouvernance

| ID | Tâche | Composant | Dépend | Effort | Statut | Preuve attendue |
|---|---|---|---|---|---|---|
| L9-1 | EBIOS RM : valeur métier « accès privilégié », événement redouté « fuite biométrique » (RGPD), scénarios (spoof, DoS face-id, flood MQTT), nouveaux biens support | `docs/ebios-rm.md` | L0-1 | M | ✅ | `docs/ebios-rm.md` : annexe consigne 1 (VM5, BS11-BS14, SO7 usurpation de visage, SO8 fuite biométrique, SO9 facteur indisponible, SO10 surfaces MQTT/admin, cotations **proposées**, résiduels) |
| L9-2 | PCA/PRA : scénario « perte du facteur biométrique » + **break-glass**, RTO/RPO, résiduels | `docs/pca-pra.md` | L0-1 | S | ✅ | `docs/pca-pra.md` : §5.7 break-glass + perte de `FACE_DATA_KEY` ⇒ réenrôlement, ligne §4.2, risque R13 ; **procédure non éprouvée (recette)** |
| L9-3 | NIS2/DORA : renforcement du contrôle d'accès (MFA/biométrie), journalisation des accès, gouvernance de la donnée biométrique | `docs/nis2-dora.md` | L0-1 | S | ⬜ | mapping mis à jour |

## L10 — Recette & e2e

| ID | Tâche | Composant | Dépend | Effort | Statut | Preuve attendue |
|---|---|---|---|---|---|---|
| L10-1 | e2e **chemin heureux** : identifiant → visage (fake recognizer) → mdp → back-office ouvert + LED `auth_ok` | `tests/e2e` | L3-4, L5-2 | M | ⬜ | test e2e vert (skip hors stack) |
| L10-2 | e2e **chemins de rejet** : non reconnu (rouge 30 s, retry, lock 5 min) ; mauvais mdp (rouge ×10, relance) | `tests/e2e` | L10-1 | M | ⬜ | tests e2e des 2 branches |
| L10-3 | **Non-régression ZTR** : `verify_tx` + boucle détection→remédiation **inchangés et verts**, indépendants du visage (G10) | `tests/e2e`, `scripts/` | L2-6 | S | ⬜ | suite ZTR existante rejouée verte |
| L10-4 | **Checklist recette matérielle** : caméra USB sur l'hôte, ESP connecté au PA, LED off par défaut, broker live, 5 états observés | `docs/` (runbook) | L4-4, L7-2 | M | ⬜ | runbook coché sur le PC Hôte |
| L10-5 | Mise à jour `ROADMAP.md` (Phase 9) + preuves consolidées de la consigne | `ROADMAP.md` | tout | S | ✅ | `ROADMAP.md` Phase 9 mise à jour avec les preuves de l'intégration (cette roadmap, ADR 0007, contrat §5) |

---

## Intégration de bout en bout (2026-10-20) — preuves et reste à faire

Branche `feat/face-auth-integration` (`5c425c6..66f685d`, 15 commits). Design : [`superpowers/specs/2026-10-20-face-auth-integration-design.md`](superpowers/specs/2026-10-20-face-auth-integration-design.md) ; décisions D1-D10 : ADR [0007](adr/0007-acces-hote-vivacite-poses-photos-chiffrees.md) (D2, D4, D5) et conception.

| Lot | Commits |
|---|---|
| L0 / L8-2 (modèle de données, events, chiffrement, Recognizer v2) | `01bf28b`, `64cad40`, `2f34384` |
| L1 (`face-id` v2) | `cb0240b` |
| L2 / L5-2 (`auth` : poses, cooldowns, MQTT) | `96ae104`, `1c6ed48` |
| L6 (API admin, bootstrap) | `02eb3ce`, `9db026a` |
| L3 (back-office : thème/API, FaceScanner, login v2, habilitations) | `44ad9e5`, `37c176d`, `30be1d5`, `b0c8092`, `ce30e9a` |
| L5-1 / L7 (compose, WAF 9443, mosquitto, SOPS) | `be727ad`, `66f685d` |

**Suites vertes (poste de dev, hors stack) :** `auth` 186 · `face-id` 93 · `resilience_db` 10 · `resilience_common` 5 (events ↔ contrat) · infra + WAF 54 · back-office Vitest 131.

**Reste à faire — recette sur le PC Hôte (rien de ceci n'a été validé) :** caméra USB réelle et **calibrage des marges de capture** (client 0,07 / 0,22 vs serveur 0,10 / 0,15) ; **build Docker de `face-id` (dlib)** et smoke du modèle `team` ; `docker compose config/up` et `nginx -t` ; prise en compte de `MODSEC_REQ_BODY_*` ; démarrage du broker ; **ESP8266 physique** synchronisé avec le jumeau LED ; scrape Prometheus et logs Loki des nouveaux services ; checklist du README back-office (§ Recette). **Reste hors recette :** L7-4 (`make test`), L8-1 (revue sécurité du flux), L8-3 (`audit.sh`), L9-3 (NIS2/DORA), L10-1 à L10-4 (e2e et runbook), validation de l'amendement RGPD par l'équipe (Yanis).

---

## Revue de sécurité & correction (2026-10-20)

Deux revues (agent sécurité du projet + revue de correction) sur L0–L3. **Correctifs appliqués et testés** :

| # | Finding | Correctif | Preuve |
|---|---|---|---|
| B1 | Verrou vérifié seulement à `/identify` (contournable via challenges pré-créés) | Vérification du verrou au **début de chaque étape** (`/face`, `/password`) | `test_lockout_is_enforced_on_prebuilt_challenges` |
| B2 | `Permissions-Policy: camera=()` casse `getUserMedia` | `camera=(self)` | `security-headers.conf` |
| M-a | `face-id /verify` non authentifié + expose le `score` | `X-Internal-Token` requis + réponse réduite à `{match, model_version}` | `test_verify_requires_internal_token` |
| M-b | Pas de rate-limit, stores non bornés, timeout face long | `@limiter.limit` sur les 3 routes + purge/plafond des stores + timeout 2 s | `challenge.py`, `backoffice.py` |
| M-c | Usage unique non atomique (TOCTOU) | `take()` atomique (`threading.Lock`) + réinsertion si l'étape avance | `challenge.py` |
| M-d | Pas de limite de taille sur `image_b64` | `max_length` (~1 Mo) côté auth et face-id | `schemas.py`, `face_id/main.py` |
| M-e | Backend `stub` par défaut silencieux | `build_recognizer` refuse `stub` sauf `ALLOW_STUB_RECOGNIZER=1` | `recognizer.py` |
| F3 | Métrique/journal de verrou sur-comptés | `just_locked` (transition uniquement) | `challenge.py` |
| F4/F5 | Fuite caméra si `getUserMedia` résout après `stop()` ; trame noire si non démarrée | drapeau d'annulation + `capture()` échoue sans flux ; retour identifiant si `start()` échoue | `useCamera.ts`, `LoginPage.tsx` |
| m1–m8 | `compare_digest` non-ASCII (500), `revoke` 204 cassé, `/ready` fuit l'erreur DB, fenêtre glissante des échecs, doc rejeu, écart contrat §5.2 (`step:"identify"`), dérive modèle, warning mode dégradé | tous corrigés | tests auth/face-id |

**Reporté au lot L7 (infra, sans objet hors stack)** : **M-f** le WAF doit router `/api/v1/auth/*` vers `auth` (+ vhost back-office) et **m9** canal auth→face-id en clair (réseau `app` interne). Ajoutés au périmètre de L7-1/L5-1.

Suites vertes après correctifs : **auth 50 · face-id 16 · back-office 14 · resilience_db 8** (+ payment-api 65 non régressé).

## Suivi

- Mettre à jour **ce tableau** et la **barre de progression** à chaque ticket clos (étape 4 de la DoD).
- Ne jamais passer un ticket à ✅ si ses tests ne sont pas verts ou si la doc n'est pas à jour.
- Garder la discipline de commits `type(scope): sujet` (ex. `feat(face-id): endpoint de vérification 1:1`, `feat(iot): machine à états LED`, `feat(backoffice): login à étapes`).
- Les tâches **testables hors stack** (logique challenge, machine à états firmware `native`, parseurs) sont faites et vérifiées sur le poste de dev ; le **live** (modèle réel, caméra, ESP, broker) est validé en recette sur le PC Hôte.
