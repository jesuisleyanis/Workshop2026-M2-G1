# Roadmap — Consigne Additionnelle 1 (auth back-office : visage + LED)

> Backlog ordonné et **suivi d'avancement** de la [Consigne Additionnelle 1](consigne-additionnelle-1.md).
> **Definition of Done par ticket** (non négociable, cf. `CLAUDE.md`) : ① code conforme aux contrats · ② tests **verts** · ③ doc (CDC/README du composant + doc transverse si une interface bouge) · ④ cette ligne mise à jour (statut + preuve). La commande `/avancer` et la skill `resilience-component` outillent chaque ticket.
> Légende : ⬜ à faire · 🟨 en cours · ✅ fait · 🔴 bloqué · ⏭️ reporté. Effort : **S** < 0,5 j · **M** ~1 j · **L** > 1 j.

## Tableau de bord

```
L0  Cadrage & contrats     [##########] 100%  contrat + ADR + modèle données (migration) — tests verts
L1  Service face-id        [#########.]  90%  service + 15 tests verts + point de branchement modèle équipe (INTEGRATION-ML.md) ; modèle réel en recette
L2  Auth à étapes          [##########] 100%  identifiant→visage→mdp + verrouillage 1 reprise/5 min — 13 tests verts  ✅
L3  Back-office + webcam    [########..]  80%  login à étapes + webcam + miroir LED livrés (14 tests Vitest) ; reste écran habilitations (L6)
L4  Firmware ESP8266        [######....]  60%  machine à états + tests native + firmware posés ; recette matérielle à faire
L5  Transport MQTT          [####......]  40%  config broker durcie + ACL posées ; service Compose + client auth à câbler
L6  Habilitations           [..........]   0%   rôles + enrôlement/révocation visage
L7  Infra & observabilité   [..........]   0%   compose, Prometheus, SOPS, durcissement
L8  Sécurité & RGPD         [..........]   0%   biométrie, liveness résiduel, surface MQTT/caméra
L9  Gouvernance             [..........]   0%   EBIOS / PCA-PRA / NIS2-DORA
L10 Recette & e2e           [..........]   0%   flux complet + ZTR inchangé + checklist matériel
```

**Chemin critique :** L0 ✅ → **L2** (prochain) → L3 → L10. Parallélisables : L1 (fait), L4 (logique faite), L5, L7, L9.
**Fondations posées** (2026-10-20) : contrat + modèle de données + service `face-id` (testé) + logique firmware (testée) + config broker. Prochaine étape : **L2** (auth à étapes), qui consomme `face-id` déjà livré.

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
| L1-2 | Abstraction `Recognizer` (embed + compare) avec **backend InsightFace `buffalo_s`** et **stub déterministe** injectable pour les tests | `services/face-id` | L1-1 | L | ✅ | `recognizer.py` (stub centré + cosine) + `backends/insightface_backend.py` ; tests match/no-match déterministes. **Smoke modèle réel en recette** |
| L1-3 | `POST /verify` (1:1, `{username,image_b64}`→`{match,score,threshold,model_version}`) + events `face_verify_*` + métriques | `services/face-id` | L1-2, L0-3 | ✅ | `test_enroll_then_verify_matches_same_face`, `…rejects_a_different_face`, anti-énumération, garde `model_version` |
| L1-4 | `POST /enroll`, `DELETE /enroll/{username}`, `GET /enrollments` (token interne) — **embedding seul**, **aucune image renvoyée** | `services/face-id` | L1-3 | ✅ | `store.py` + routes ; `test_enrollments_list_exposes_no_biometric_data`, `test_revoke_deletes_enrollment`, token requis |
| L1-5 | Dockerfile durci (slim, non-root, modèle épinglé au build) + requirements épinglés | `services/face-id` | L1-4 | ✅ | `Dockerfile` (uid 10001, read_only, healthcheck) + `requirements.txt` épinglés. **Build live en recette** |

> **L1 — 10 tests verts** (`PYTHONPATH=services/face-id/src pytest services/face-id/tests`). Backend réel `insightface` écrit mais non smoke-testé hors stack (deps non installées) : validation en recette.

## L2 — Authentification à étapes *(chemin critique)*

| ID | Tâche | Composant | Dépend | Effort | Statut | Preuve attendue |
|---|---|---|---|---|---|---|
| L2-1 | Store de challenge en mémoire (TTL, usage unique par étape) + machine à états §5.1 | `services/auth` | L0-1 | M | ✅ | `challenge.py` (ChallengeStore/LockoutStore, horloge injectable) ; tests cycle + expiration + rejeu refusé |
| L2-2 | `POST /auth/identify` (toujours 200 hors lockout, **anti-énumération**) + event + caméra ON | `services/auth` | L2-1 | S | ✅ | `test_identify_unknown_user_still_returns_a_challenge` |
| L2-3 | `POST /auth/face` → appelle `face-id /verify` ; match→PASSWORD, no-match→IDENTIFY + compteur | `services/auth` | L2-2, L1-3 | ✅ | `HttpFaceVerifier` + stub injectable ; transitions, rejeu, `auth_face_steps_total`, 503 si face-id down |
| L2-4 | `POST /auth/password` (valide seulement en step PASSWORD) → JWT + **contrôle de rôle** ; KO→IDENTIFY | `services/auth` | L2-3 | ✅ | rôle dans le JWT ; saut d'étape 409, rôle non privilégié 403, mauvais mdp 401 + LED auth_fail |
| L2-5 | **Verrouillage** (CA4) : 2 échecs/cycle → **5 min** par `(username, ip)` + `429 Retry-After` + event `auth_locked_out` | `services/auth` | L2-3 | ✅ | `test_lockout_after_one_retry_then_5_minutes` (+ reset au succès, déblocage après délai) |
| L2-6 | `/login` **conservé** pour comptes de service / front client (D4) + non-régression auth | `services/auth` | L2-1 | ✅ | `test_legacy_login_still_works` ; 36 tests auth d'origine toujours verts (49 au total) |

> **L2 — 13 tests verts** (`services/auth/tests/test_auth_stepped.py`) ; suite auth complète **49 verts**. LED émise via un notifieur injectable (fail-open) — le backend MQTT réel est L5-2. Le contrôle de rôle anticipe L6-1.
>
> **Point de branchement du modèle de l'équipe** (lié à L1-2) : `face-id` isole le modèle derrière l'interface `Recognizer`. Gabarit `backends/team_backend.py` + backend `team` + **`services/face-id/INTEGRATION-ML.md`** (contrat `embed()` + test de conformité) : le modèle du coéquipier se branche sans toucher au reste.

## L3 — Back-office + capture webcam *(chemin critique)*

| ID | Tâche | Composant | Dépend | Effort | Statut | Preuve attendue |
|---|---|---|---|---|---|---|
| L3-1 | Scaffold app React/Vite/TS/Tailwind `services/backoffice` (CDC + README + client API auth) | `services/backoffice` | L0-2 | M | ✅ | Vite 8 + React 19 + Tailwind 4 + Vitest ; `api/auth.ts` (client §5.2) ; lint + build + typecheck OK |
| L3-2 | Page login à étapes : saisie identifiant → **`getUserMedia`** (caméra hôte) → envoi trame → saisie mdp conditionnelle | `services/backoffice` | L3-1, L2-4 | L | ✅ | `LoginPage` + `useCamera` ; vitest (getUserMedia **mocké**) : ordre imposé, vidage sur rejet, caméra OFF, happy path, rôle refusé |
| L3-3 | Témoin d'état miroir de la LED + messages (reconnu / non reconnu / blocage 5 min) | `services/backoffice` | L3-2 | S | ✅ | `LedIndicator` + `lib/led.ts` (5 états) ; vitest LED + message de blocage 429 |
| L3-4 | Écran **habilitations** (liste users/rôles, enrôlement par webcam, révocation) gated `admin` | `services/backoffice` | L3-2, L6-2 | L | ⬜ | **dépend de L6** — placeholder dans l'accueil |
| L3-5 | Dockerfile durci + route WAF dédiée (`/admin` ou vhost), `read_only`+tmpfs (parité front) | `services/backoffice`, `security/waf` | L3-2 | M | 🟨 | Dockerfile nginx non-root 8080 + headers (parité front) ; **route WAF** à câbler (L7) |

> **L3 — 14 tests Vitest verts** (`npm test`), lint + `tsc` + `vite build` OK. Login à étapes complet (ordre imposé serveur, caméra coupée hors scan, miroir LED, blocage 5 min). Reste l'écran habilitations (L3-4, après L6).

## L4 — Firmware ESP8266 (LED bicolore)

| ID | Tâche | Composant | Dépend | Effort | Statut | Preuve attendue |
|---|---|---|---|---|---|---|
| L4-1 | Projet PlatformIO (CLion) : `platformio.ini` (env carte **+ env `native`**), CDC + README + câblage LED | `iot/esp8266-led` | L0-2 | M | ✅ | `platformio.ini` (nodemcuv2 + native) + CDC + README (câblage D1/D2) |
| L4-2 | **Machine à états LED** §5.2 non bloquante (`millis()`), découplée du transport | `iot/esp8266-led` | L4-1 | ✅ | `lib/led/led_controller.{h,cpp}` (logique pure) + `test/` Unity : 5 états, timings 30 s / ×10, défaut off, parseur ; **6 tests native verts** |
| L4-3 | WiFi (PA `RESILIENCE-G<n>`) + client MQTT (subscribe `cmd`, publish `status`/LWT), `secrets.h` depuis template **gitignored** | `iot/esp8266-led` | L4-2, L5-1 | 🟨 | modules Wi-Fi/MQTT séparés, 3 routes HTTP directes ; build ESP8266 + 6 tests native verts ; **recette live** (connexion + réception) à faire |
| L4-4 | Robustesse : reconnexion WiFi/MQTT, LED off au boot, heartbeat | `iot/esp8266-led` | L4-3 | 🟨 | Wi-Fi sans attente active, tentatives Wi-Fi/MQTT espacées, LED off au boot + heartbeat codés ; **recette coupure/reprise** à faire |

## L5 — Transport MQTT

| ID | Tâche | Composant | Dépend | Effort | Statut | Preuve attendue |
|---|---|---|---|---|---|---|
| L5-1 | Broker **Mosquitto** durci : `allow_anonymous false`, user/mdp SOPS, **ACL par topic**, bind interface hotspot, image épinglée | `infra/compose`, `security/*` | L0-1 | 🟨 | service Compose `iot` + génération passwd en tmpfs + test contrat et smoke auth→led ; **recette sur PA réel** à faire |
| L5-2 | Client MQTT dans `auth` : publie les états §5.2, **fail-open** (broker down ⇒ auth continue), events `led_*` | `services/auth` | L5-1, L2-3 | M | ⬜ | tests publication (mock) + **cas broker injoignable** + `resilience_led_publish_total` |

## L6 — Habilitations (rôles + enrôlement)

| ID | Tâche | Composant | Dépend | Effort | Statut | Preuve attendue |
|---|---|---|---|---|---|---|
| L6-1 | Rôles (`customer`/`operator`/`admin`) exploités par auth (claim JWT + garde back-office) | `services/auth`, `resilience_db` | L0-3 | M | ⬜ | tests : rôle dans le JWT, accès back-office réservé |
| L6-2 | Orchestration enrôlement : back-office → auth (token interne) → `face-id /enroll` ; traçabilité `enrolled_by` | `services/auth`, `services/face-id` | L6-1, L1-4 | M | ⬜ | tests chaîne enrôlement + audit `enrolled_by` |
| L6-3 | Seed : au moins un `admin` enrôlable pour la démo (visage de démo fictif documenté) | `scripts/`, `resilience_db` | L6-2 | S | ⬜ | `seed` crée un opérateur ; procédure d'enrôlement de démo |

## L7 — Infra & observabilité

| ID | Tâche | Composant | Dépend | Effort | Statut | Preuve attendue |
|---|---|---|---|---|---|---|
| L7-1 | Compose : `face-id`, `backoffice`, `mosquitto` (réseaux, profils, dépendances, durcissement, healthchecks) ; **WAF route `/api/v1/auth/*` → auth + vhost back-office (M-f)** ; réseau `app` interne (m9) | `infra/compose`, `security/waf` | L1-5, L3-5, L5-1 | M | ⬜ | `test_compose_hardening` étendu ; images épinglées (R5) ; route WAF testée |
| L7-2 | Prometheus scrape `face-id` ; vérifier que Promtail capte les logs des nouveaux services | `infra/prometheus`, `infra/promtail` | L7-1 | S | ⬜ | cible scrappée + logs dans Loki (recette) |
| L7-3 | SOPS : `MQTT_*`, **`FACE_INTERNAL_TOKEN` (même valeur sur `auth` et `face-id`)**, (option) clé chiffrement embedding ; `secrets.example.env` + README | `security/sops` | L5-1 | S | ⬜ | exemples factices ; audit « aucun secret en clair » ; token partagé vérifié (sinon 503 à l'étape visage) |
| L7-4 | Makefile/aliases : build modèle face-id, lancement broker ; `make test` agrège les nouveaux composants | `Makefile`, `README.md` | L7-1 | S | ⬜ | `make test` intègre face-id + backoffice ; doc |

## L8 — Sécurité & RGPD

| ID | Tâche | Composant | Dépend | Effort | Statut | Preuve attendue |
|---|---|---|---|---|---|---|
| L8-1 | Revue `security-reviewer` du flux (surface MQTT/caméra, privilèges, pas de bypass visage, anti-énumération, fail-open) | tous | L2-5, L5-2, L3-5 | M | ⬜ | rapport de revue + correctifs |
| L8-2 | RGPD : embedding seul, (option) chiffrement au repos, effacement, rétention — tracé dans la doc | `services/face-id`, `docs/` | L1-4 | S | ⬜ | section RGPD + test « no image persisted » |
| L8-3 | Durcissement confirmé : `audit.sh` couvre face-id/backoffice/mosquitto (non-root, cap_drop, read_only, exposition) | `security/hardening` | L7-1 | S | ⬜ | `audit.sh` exit 0 |
| L8-4 | (Option) Signal SOC : règle Loki sur rafale `face_verify_nomatch`/`auth_face_rejected` | `infra/grafana\|loki` | L2-5 | S | ⏭️ | règle + test (si retenu) |

## L9 — Gouvernance

| ID | Tâche | Composant | Dépend | Effort | Statut | Preuve attendue |
|---|---|---|---|---|---|---|
| L9-1 | EBIOS RM : valeur métier « accès privilégié », événement redouté « fuite biométrique » (RGPD), scénarios (spoof, DoS face-id, flood MQTT), nouveaux biens support | `docs/ebios-rm.md` | L0-1 | M | ⬜ | section dédiée reliée à l'archi réelle |
| L9-2 | PCA/PRA : scénario « perte du facteur biométrique » + **break-glass**, RTO/RPO, résiduels | `docs/pca-pra.md` | L0-1 | S | ⬜ | procédure break-glass + RTO/RPO |
| L9-3 | NIS2/DORA : renforcement du contrôle d'accès (MFA/biométrie), journalisation des accès, gouvernance de la donnée biométrique | `docs/nis2-dora.md` | L0-1 | S | ⬜ | mapping mis à jour |

## L10 — Recette & e2e

| ID | Tâche | Composant | Dépend | Effort | Statut | Preuve attendue |
|---|---|---|---|---|---|---|
| L10-1 | e2e **chemin heureux** : identifiant → visage (fake recognizer) → mdp → back-office ouvert + LED `auth_ok` | `tests/e2e` | L3-4, L5-2 | M | ⬜ | test e2e vert (skip hors stack) |
| L10-2 | e2e **chemins de rejet** : non reconnu (rouge 30 s, retry, lock 5 min) ; mauvais mdp (rouge ×10, relance) | `tests/e2e` | L10-1 | M | ⬜ | tests e2e des 2 branches |
| L10-3 | **Non-régression ZTR** : `verify_tx` + boucle détection→remédiation **inchangés et verts**, indépendants du visage (G10) | `tests/e2e`, `scripts/` | L2-6 | S | ⬜ | suite ZTR existante rejouée verte |
| L10-4 | **Checklist recette matérielle** : caméra USB sur l'hôte, ESP connecté au PA, LED off par défaut, broker live, 5 états observés | `docs/` (runbook) | L4-4, L7-2 | M | ⬜ | runbook coché sur le PC Hôte |
| L10-5 | Mise à jour `ROADMAP.md` (Phase 9) + preuves consolidées de la consigne | `ROADMAP.md` | tout | S | ⬜ | Phase 9 à jour |

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
