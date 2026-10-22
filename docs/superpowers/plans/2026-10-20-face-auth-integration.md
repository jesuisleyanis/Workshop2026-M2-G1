# Face Auth Integration — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Brancher le modèle de reconnaissance de l'équipe (vivacité 3 poses) dans l'auth à étapes du back-office, ajouter inscription avec photos + habilitations + bootstrap, piloter l'ESP8266 via MQTT, câbler l'infra, et styliser (sci-fi) uniquement l'étape de scan facial.

**Architecture:** `face-id` (FastAPI) analyse les images (embedding + pose) et stocke des gabarits/photos chiffrés AES-GCM ; `auth` orchestre le challenge (ordre de poses aléatoire, refroidissements, verrouillage), publie la LED en MQTT et expose l'API admin/bootstrap ; `backoffice` (React) capture via `getUserMedia` avec guidage MediaPipe et n'est joignable que via un listener WAF `127.0.0.1:9443`.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2 / Alembic, `cryptography` (AESGCM), `paho-mqtt` 2.x, `face_recognition` 1.3.0 / dlib 20.0.1 (backend `team`), React 19 + Vite 8 + Tailwind 4 + Vitest 5, `@mediapipe/tasks-vision`, Nginx/ModSecurity, Mosquitto 2.

**Spec:** `docs/superpowers/specs/2026-10-20-face-auth-integration-design.md`

## Global Constraints

- Ne PAS modifier : `dashboard/`, `services/front/`, `remediation/`, `ml/`, `scripts/verify_tx*`, `POST /api/v1/login`.
- Back-office : tokens/polices **identiques au front** (`services/front/src/index.css`) ; sci-fi **uniquement** dans `FaceScanner`.
- Logs : uniquement des `event` de `RESERVED_EVENTS` ; jamais d'image, d'embedding, de mot de passe ou de token dans un log.
- Métriques : préfixe `resilience_`, déclarées dans `libs/python/resilience_common/src/resilience_common/metrics.py`.
- Secrets : jamais en clair/commités ; variantes `*_FILE` ; exemples factices seulement dans `security/sops/secrets.example.env`.
- Poses : clés exactes `face`, `gauche`, `droite`. Seuils pose : `|rot| <= 0.10` face, `rot >= 0.15` gauche, `rot <= -0.15` droite. Seuil identité `team` : distance euclidienne `<= 0.6`.
- Timings : refroidissement visage refusé **30 s** (`BACKOFFICE_REJECT_COOLDOWN=30`), mot de passe refusé **3 s** (`BACKOFFICE_FAIL_COOLDOWN=3`), verrouillage 2 échecs → **300 s**.
- Tests Python : un process pytest par composant, lancé **depuis le répertoire du composant**, interpréteur `$PY` = `C:/Users/Louis/AppData/Local/Temp/claude/L--EPSI--Master2-Workshop/f146e577-3de3-401a-b152-f5036e25b79e/scratchpad/venv/Scripts/python.exe` (`$PY -m pytest -q -p no:cacheprovider`).
- Tests front : Node 24 requis → `export PATH="/c/Users/Louis/AppData/Local/Temp/claude/L--EPSI--Master2-Workshop/f146e577-3de3-401a-b152-f5036e25b79e/scratchpad/node24/node-v24.11.0-win-x64:$PATH"` puis `npx vitest run`, `npx tsc --noEmit`, `npx eslint .` dans `services/backoffice`.
- Commits : `type(scope): sujet` en français, terminés par `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Les sous-agents **ne commitent pas** : le coordinateur commite après revue.
- Baseline verte avant travaux : auth 54, face-id 16, backoffice 14, resilience_db 8, resilience_common 5.

---

## File Structure

```
libs/python/resilience_common/src/resilience_common/events.py      (+ events)            T1
libs/python/resilience_db/src/resilience_db/models.py               (+ photos, poses)     T1
libs/python/resilience_db/src/resilience_db/migrations/versions/0003_face_templates_encrypted.py  T1
services/face-id/src/face_id/poses.py          pose (rotation nez/mâchoire)                T1
services/face-id/src/face_id/crypto.py         AES-GCM sealed blobs                         T1
services/face-id/src/face_id/recognizer.py     Recognizer v2 + StubRecognizer v2            T1
services/face-id/src/face_id/backends/team_backend.py   face_recognition (Valentin)        T1
services/face-id/src/face_id/backends/insightface_backend.py  analyze() v2                 T1
services/face-id/src/face_id/store.py          gabarits/photos chiffrés                     T2
services/face-id/src/face_id/enrollment.py     validation de série + vérification séquence  T2
services/face-id/src/face_id/main.py           routes v2                                    T2
services/face-id/{Dockerfile,requirements*.txt,README,CDC,INTEGRATION-ML}.md               T2
services/auth/src/auth_service/challenge.py    poses + CooldownStore                        T3
services/auth/src/auth_service/backoffice.py   identify/face v2 + cooldown                  T3
services/auth/src/auth_service/face_client.py  client HTTP face-id (verify/enroll/...)      T3
services/auth/src/auth_service/led_mqtt.py     MqttLedNotifier + statut LWT                 T4
services/auth/src/auth_service/admin.py        API admin + bootstrap                        T5
services/backoffice/src/index.css, main.tsx, components/Brand.tsx       thème front        T6
services/backoffice/src/api/{http,auth,admin}.ts                         clients API       T6
services/backoffice/src/lib/pose.ts            rotation/pose (miroir de poses.py)          T6
services/backoffice/src/vision/{detector.ts,mediapipe.ts}                détecteur pose    T7
services/backoffice/src/components/scanner/*   FaceScanner sci-fi                          T7
services/backoffice/src/pages/LoginPage.tsx    login v2                                    T8
services/backoffice/src/pages/{HabilitationsPage,BootstrapPage}.tsx, components/EnrollWizard.tsx  T9
infra/compose/docker-compose.yml, security/waf/nginx.conf, infra/mosquitto/*, security/sops/secrets.example.env, infra/prometheus  T10
docs/contracts.md §5, docs/adr/0007-*.md, docs/consigne-additionnelle-1*.md, ROADMAP.md                                         T11
```

---

### Task 1: Fondations biométriques (events, DB, poses, crypto, Recognizer v2)

**Files:**
- Modify: `libs/python/resilience_common/src/resilience_common/events.py`, `docs/contracts.md` (tableau §1 « Événements normalisés » uniquement)
- Modify: `libs/python/resilience_db/src/resilience_db/models.py` ; Create: `.../migrations/versions/0003_face_templates_encrypted.py` ; Test: `libs/python/resilience_db/tests/test_db.py`
- Create: `services/face-id/src/face_id/poses.py`, `services/face-id/src/face_id/crypto.py`
- Modify: `services/face-id/src/face_id/recognizer.py`, `backends/team_backend.py`, `backends/insightface_backend.py`
- Test: `services/face-id/tests/test_poses.py`, `test_crypto.py`, `test_recognizer_contract.py`

**Interfaces — Produces:**
```python
# events (ajout à RESERVED_EVENTS + lignes du tableau contracts.md §1, service indiqué)
"auth_cooldown"(auth) "admin_user_created"(auth) "admin_role_changed"(auth)
"admin_face_enrolled"(auth) "admin_face_revoked"(auth) "backoffice_bootstrap"(auth)
"face_photos_viewed"(face-id) "face_enrollment_rejected"(face-id)

# resilience_db.models.FaceEnrollment : + photos: Mapped[bytes|None] (LargeBinary, nullable)
#                                       + poses: Mapped[str] (String(64), default "face", server_default "face")
#   `embedding` contient désormais un blob scellé (crypto.seal) des gabarits par pose.
# Migration 0003 (down_revision "0002") : batch add_column photos + poses ; downgrade drop.

# face_id/poses.py
POSES: tuple[str, ...] = ("face", "gauche", "droite")
SEUIL_FACE = 0.10; SEUIL_PROFIL = 0.15
def rotation_from_points(jaw_left_x: float, jaw_right_x: float, nose_xs: list[float]) -> float | None
def pose_from_rotation(rotation: float | None) -> str | None   # "face"|"gauche"|"droite"|None

# face_id/crypto.py
class SealError(ValueError): ...
class Sealer:
    def __init__(self, key: bytes): ...          # 32 octets, sinon ValueError
    @classmethod
    def from_b64(cls, key_b64: str) -> "Sealer": ...
    def seal(self, plaintext: bytes, aad: bytes) -> bytes: ...   # b"v1" + nonce(12) + ct
    def open(self, blob: bytes, aad: bytes) -> bytes: ...        # SealError si altéré / mauvaise clé
def pack_templates(templates: dict[str, list[float]]) -> bytes   # JSON compact trié
def unpack_templates(raw: bytes) -> dict[str, list[float]]
def pack_photos(photos: dict[str, bytes]) -> bytes               # JSON {pose: b64}
def unpack_photos(raw: bytes) -> dict[str, bytes]

# face_id/recognizer.py
class NoFaceError(ValueError)
class MultipleFacesError(ValueError)
@dataclass(frozen=True) class FaceSample: embedding: list[float]; pose: str | None
class Recognizer(Protocol):
    model_version: str; threshold: float          # distance max (plus petit = plus proche)
    def analyze(self, image: bytes, *, precise: bool = False) -> FaceSample: ...
    def distance(self, a: list[float], b: list[float]) -> float: ...
class StubRecognizer:   # images de test = b"<pose>|<identite>" (ex. b"face|alice") ; b"none" -> NoFaceError ;
                        # b"many" -> MultipleFacesError ; pose "x" -> pose None ; embedding déterministe de l'identité seule
    model_version = "stub-2.0"; threshold = 0.6 ; distance = euclidienne
def euclidean(a, b) -> float
def build_recognizer(backend: str, threshold: float | None = None) -> Recognizer  # garde ALLOW_STUB_RECOGNIZER conservée
```

- [ ] **Step 1: Tests `test_poses.py`** — cas : rotation 0 → `face` ; 0.2 → `gauche` ; -0.2 → `droite` ; 0.12 → `None` ; largeur ≤ 0 → `None`. Formule : `(mean(nose_xs) - jaw_left_x) / (jaw_right_x - jaw_left_x) - 0.5`.
- [ ] **Step 2: Tests `test_crypto.py`** — round-trip seal/open ; blob ≠ clair et commence par `b"v1"` ; mauvaise clé → `SealError` ; AAD différente → `SealError` ; clé de 16 octets → `ValueError` ; `pack/unpack_templates` et `pack/unpack_photos` round-trip.
- [ ] **Step 3: Adapter `test_recognizer_contract.py`** au contrat v2 (StubRecognizer : même identité/pose différente → distance 0 ; identités différentes → distance > threshold ; `b"none"` → NoFaceError ; `b"many"` → MultipleFacesError ; pose lue).
- [ ] **Step 4: Run** `cd services/face-id && $PY -m pytest -q -p no:cacheprovider tests/test_poses.py tests/test_crypto.py tests/test_recognizer_contract.py` → FAIL (modules absents).
- [ ] **Step 5: Implémenter** `poses.py`, `crypto.py` (`cryptography.hazmat.primitives.ciphers.aead.AESGCM`, `os.urandom(12)`), `recognizer.py` v2. Stub : embedding = 16 floats dérivés de `sha256(identite)` ∈ [-1,1] mis à l'échelle ×1.0 (deux identités ≠ ⇒ distance ≫ 0.6). `TeamRecognizer` (backend `team`, pragma no cover) : `face_recognition.load_image_file(BytesIO)` → `face_locations` (0 → NoFaceError, >1 → MultipleFacesError) → `face_landmarks` → `rotation_from_points(chin[0][0], chin[-1][0], [p[0] for p in nose_tip])` → `face_encodings(img, [loc], num_jitters=5 if precise else 1)` ; `model_version = "team-dlib-face_recognition-1.3.0"`, `threshold=0.6`, `distance` = `face_recognition.face_distance`. Insightface : `analyze` via `app.get` (kps 5 points : pose depuis x du nez vs yeux, même seuils), distance = `1 - cosine`, threshold 0.65 (pragma no cover).
- [ ] **Step 6: events + contrat §1** (ajouter les 8 events au frozenset et 8 lignes au tableau §1 entre `face_enrollment_revoked` et `transaction_created`).
- [ ] **Step 7: Migration 0003 + modèle** + test `test_db.py` : `test_face_enrollment_has_photos_and_poses_columns` (insertion avec photos=b"x", poses="face,gauche,droite", relecture).
- [ ] **Step 8: Run** face-id (nouveaux tests verts ; les anciens tests `test_face_id.py` cassés sont réécrits en T2 — ne pas les corriger ici sauf l'import), `resilience_db` 9 verts, `resilience_common` verts (`test_reserved_events_match_contract_table`).
- [ ] **Step 9: Ajouter** `cryptography==44.0.0` à `services/face-id/requirements.txt`.

---

### Task 2: `face-id` v2 — enrôlement 3 poses, vérification de séquence, photos chiffrées, image Docker dlib

**Files:**
- Create: `services/face-id/src/face_id/enrollment.py`
- Modify: `services/face-id/src/face_id/store.py`, `main.py`, `config.py`
- Modify: `services/face-id/tests/conftest.py`, `tests/test_face_id.py`
- Modify: `services/face-id/Dockerfile`, `requirements.txt` ; Create: `requirements-team.txt`
- Modify docs: `services/face-id/README.md`, `CAHIER-DES-CHARGES.md`, `INTEGRATION-ML.md`

**Interfaces — Consumes:** T1 (`Recognizer`, `FaceSample`, `Sealer`, `pack_*`, `POSES`).
**Produces (HTTP, tous `X-Internal-Token`) :**
```
POST /api/v1/enroll   {username, enrolled_by, poses:{face,gauche,droite: <b64>}}
   200 {enrolled:true, model_version, poses:["face","gauche","droite"]}
   422 {"error":{"code":"enrollment_rejected","message":"...","details":[{"pose":"gauche","reason":"wrong_pose"}]}}
        reason ∈ no_face | multiple_faces | wrong_pose | inconsistent | invalid_image | missing
   404 {"error":{"code":"unknown_user",...}}
POST /api/v1/verify   {username, frames:[{pose, image_b64}] (exactement 3, poses distinctes ∈ POSES)}
   200 {match: bool, model_version}       (motif d'échec seulement dans les logs : face_verify_nomatch / face_verify_error)
DELETE /api/v1/enroll/{username}  204 | 404 not_enrolled
GET /api/v1/enrollments           [{username, enrolled_at, enrolled_by, model_version, poses}]
GET /api/v1/enrollments/{username}/photos?viewer=<admin>   200 {photos:{face:<b64>,gauche:..,droite:..}} | 404
```
Erreurs au format contrat `{"error":{"code","message"}}` (handler `HTTPException` → ce format ; conserver les codes `internal_token_invalid` 401, `no_face_detected` n'est plus utilisé).

```python
# enrollment.py
@dataclass class PoseIssue: pose: str; reason: str
class EnrollmentRejected(ValueError): issues: list[PoseIssue]
def build_templates(recognizer, images: dict[str, bytes]) -> dict[str, list[float]]
    # pour chaque pose de POSES : analyze(precise=True) ; pose == attendue ; puis gauche/droite vs face <= threshold
    # lève EnrollmentRejected(toutes les issues trouvées)
def verify_sequence(recognizer, templates: dict[str, list[float]], frames: list[tuple[str, bytes]]) -> tuple[bool, str]
    # (match, reason) ; reason ∈ "ok"|"no_face"|"multiple_faces"|"wrong_pose"|"face_mismatch"|"incomplete"
def thumbnail(image: bytes, max_side: int = 240) -> bytes   # Pillow JPEG q=80 ; si Pillow échoue → bytes d'origine tronqués? NON : lever ValueError
```
Store : `upsert(username, templates_blob, photos_blob, poses_csv, model_version, enrolled_by)`, `get(username) -> StoredEnrollment(templates_blob, photos_blob, model_version)`, `list()` ajoute `poses`. AAD de chiffrement = `f"{username}|templates".encode()` / `f"{username}|photos".encode()`.
Config : `face_data_key: str` lu via `_read_secret("FACE_DATA_KEY")` (base64 de 32 octets, requis — `from_env` échoue sinon) ; `Settings(..., face_data_key=...)`.
Enrôlement d'un modèle différent (`model_version` ≠) ⇒ verify renvoie `match=false` + log `face_verify_error` (comportement existant conservé).

- [ ] **Step 1: Réécrire `conftest.py`** : `KEY_B64 = base64.b64encode(b"k"*32).decode()`, `Settings(internal_token=TOKEN, recognizer_backend="stub", face_data_key=KEY_B64, run_migrations=False)`, helper `img(pose, who) -> str` = b64 de `f"{pose}|{who}"` ; Pillow non requis pour le stub : `thumbnail` doit accepter des octets non-image en mode test via paramètre `make_thumbnail` injectable dans `create_app(..., thumbnailer=None)` (défaut = `enrollment.thumbnail`; tests passent `lambda b: b`).
- [ ] **Step 2: Réécrire `test_face_id.py`** (tests nommés) :
  `test_enroll_three_poses_then_verify_in_random_order_matches`, `test_verify_rejects_other_identity`, `test_verify_rejects_wrong_pose_in_sequence`, `test_verify_requires_exactly_three_distinct_poses` (422), `test_unknown_user_verify_is_nomatch_not_404`, `test_enroll_rejects_whole_series_with_per_pose_details` (pose gauche fausse + droite `none` → 422 avec 2 détails), `test_enroll_rejects_inconsistent_identity_across_poses`, `test_enroll_unknown_user_404`, `test_templates_and_photos_are_encrypted_at_rest` (lecture brute DB : blobs commencent par `b"v1"`, ne contiennent pas `b"alice"`), `test_photos_endpoint_requires_token_and_logs_view`, `test_enrollments_list_exposes_no_biometric_data` (+ champ `poses`), `test_revoke_deletes_enrollment`, `test_verify_requires_internal_token`, `test_model_version_mismatch_is_nomatch_with_error_log`, `test_settings_require_face_data_key`, `test_logs_never_contain_image_or_embedding`, health/ready/metrics conservés, `test_all_emitted_events_belong_to_the_contract`.
- [ ] **Step 3: Run** → FAIL.
- [ ] **Step 4: Implémenter** `enrollment.py`, `store.py`, `main.py`, `config.py`. Garder limites de taille (`_MAX_IMAGE_B64 = 1_500_000` par image) et métriques existantes (`face_verifications_total{result}`, `face_verify_duration_seconds`, `face_enrollments`).
- [ ] **Step 5: Run** `cd services/face-id && $PY -m pytest -q -p no:cacheprovider` → tout vert.
- [ ] **Step 6: Docker** : builder `python:3.12-slim` + `apt-get install -y --no-install-recommends cmake build-essential` ; `pip install -r requirements.txt -r requirements-team.txt` (`requirements-team.txt` : `setuptools<81`, `dlib==20.0.1`, `face-recognition==1.3.0`, `face_recognition_models==0.3.0`, `numpy==2.2.6`, `pillow==12.2.0`) ; runtime slim : copier `/opt/venv`, `apt-get install -y --no-install-recommends libgomp1` si nécessaire, uid 10001, `ENV RECOGNIZER_BACKEND=team`, HEALTHCHECK `/health`. `pillow==12.2.0` aussi dans `requirements.txt` (thumbnail).
- [ ] **Step 7: Docs** : README (API v2, `FACE_DATA_KEY`, recette : enrôler + vérifier), CDC (critères d'acceptation mis à jour = tests ci-dessus, RGPD : photos chiffrées), INTEGRATION-ML (contrat `analyze/distance`, modèle de Valentin branché).

---

### Task 3: `auth` — challenge avec poses aléatoires, frames, refroidissements, client face-id

**Files:**
- Modify: `services/auth/src/auth_service/challenge.py`, `backoffice.py`, `schemas.py`, `config.py`, `main.py`
- Create: `services/auth/src/auth_service/face_client.py`
- Test: `services/auth/tests/test_auth_stepped.py` (mise à jour), `tests/test_face_client.py`

**Interfaces — Consumes:** API face-id T2.
**Produces:**
```python
# challenge.py
Challenge(+ poses: tuple[str, ...] = ())
ChallengeStore.create(username, *, step=FACE, poses: tuple[str, ...] = ())
class CooldownStore:                         # par client_ip
    def __init__(self, clock=time.monotonic): ...
    def start(self, ip: str | None, seconds: float, reason: str) -> None
    def remaining(self, ip: str | None) -> tuple[int, str | None]   # (secondes arrondies sup., reason) ; (0, None) sinon
# face_client.py
class FaceUnavailable(RuntimeError)
class EnrollmentRejectedError(ValueError): details: list[dict]
class FaceIdClient:
    def __init__(self, base_url: str, token: str, timeout: float = 2.0, enroll_timeout: float = 20.0)
    def verify(self, username: str, frames: list[dict]) -> bool           # 422 -> False ; autre non-200/réseau -> FaceUnavailable
    def enroll(self, username: str, poses: dict[str, str], enrolled_by: str) -> dict   # 422 enrollment_rejected -> EnrollmentRejectedError ; 404 -> LookupError
    def revoke(self, username: str) -> bool                               # 204 True, 404 False
    def enrollments(self) -> list[dict]
    def photos(self, username: str, viewer: str) -> dict[str, str] | None
# backoffice.py : `FaceVerifier.verify(username, frames: list[dict]) -> bool`; `FaceUnavailable` ré-exporté depuis face_client
# schemas.py
IdentifyResponse(+ poses: list[str])
class FaceFrame(BaseModel): pose: Literal["face","gauche","droite"]; image_b64: str = Field(min_length=1, max_length=800_000)
FaceRequest: challenge_id + frames: list[FaceFrame] = Field(min_length=3, max_length=3)
# config.py
backoffice_reject_cooldown: int = 30   # BACKOFFICE_REJECT_COOLDOWN
backoffice_fail_cooldown: int = 3      # BACKOFFICE_FAIL_COOLDOWN
```
Comportement :
- `identify` : vérifie `lockouts` puis `cooldowns.remaining(ip)` ; si > 0 → `ApiError(429, "cooldown", "Please wait", {"Retry-After": n})` + log `auth_cooldown`. Poses = `tuple(secrets.SystemRandom().sample(POSES, 3))`. Réponse inclut `poses`.
- `face` : si `[f.pose for f in frames] != list(challenge.poses)` ⇒ traité comme **non reconnu** (sans appeler face-id). Non reconnu ⇒ `cooldowns.start(ip, reject_cooldown, "not_recognized")` en plus de l'existant. Réponse ajoute `cooldown: int` (secondes) — `FaceResponse(+ cooldown: int = 0)`.
- `password` KO (401) ⇒ `cooldowns.start(ip, fail_cooldown, "auth_fail")` ; l'erreur `ApiError` porte `{"Retry-After": "3"}`.
- Mode `backoffice_face_required=False` : `poses=[]`, `camera=false` (inchangé sinon).
- `main.create_app(..., face_client: FaceIdClient | None = None, ...)` : `face_verifier` par défaut = `face_client` (un seul objet) ; `app.state.face_client` exposé pour T5.

- [ ] **Step 1: Mettre à jour `test_auth_stepped.py`** : `StubFaceVerifier.verify(username, frames)` reconnaît ssi toutes les `image_b64 == GOOD` ; helper `frames_for(identify_json, image=GOOD)` construit les frames dans l'ordre `poses` renvoyé. Nouveaux tests : `test_identify_returns_random_permutation_of_three_poses` (patch `secrets.SystemRandom.sample` ou 30 tirages → au moins 2 ordres distincts, toujours une permutation de POSES), `test_frames_out_of_order_are_rejected_without_calling_face_id`, `test_face_rejection_starts_30s_cooldown_on_identify` (429 code `cooldown`, Retry-After 30, puis OK après `clock.advance(30)`), `test_wrong_password_starts_3s_cooldown`, `test_cooldown_logs_auth_cooldown_event`, `test_face_request_requires_exactly_three_frames` (422). Adapter les tests existants à `frames`.
- [ ] **Step 2: `test_face_client.py`** avec `httpx.MockTransport` (injecter `transport` optionnel dans `FaceIdClient.__init__(..., transport=None)` → `httpx.Client(transport=...)`) : verify 200/422/500/erreur réseau ; enroll 200/422 details/404 ; revoke 204/404 ; header `X-Internal-Token` présent.
- [ ] **Step 3: Run** `cd services/auth && $PY -m pytest -q -p no:cacheprovider` → FAIL.
- [ ] **Step 4: Implémenter.** (Supprimer `HttpFaceVerifier` de `backoffice.py` au profit de `FaceIdClient`.)
- [ ] **Step 5: Run** → tout vert (≥ 54 + nouveaux).

---

### Task 4: `auth` — publication LED MQTT + statut du module

**Files:**
- Create: `services/auth/src/auth_service/led_mqtt.py`
- Modify: `services/auth/src/auth_service/config.py`, `main.py`, `backoffice.py` (route device), `requirements.txt` (`paho-mqtt==2.1.0`)
- Test: `services/auth/tests/test_led_mqtt.py`

**Produces:**
```python
LED_CMD_TOPIC = "resilience/led/cmd"; LED_STATUS_TOPIC = "resilience/led/status"
class MqttLedNotifier:
    def __init__(self, host: str, port: int, username: str, password: str, log, *, client_factory=None, clock=...): ...
        # client_factory() -> objet compatible paho Client (tests : FakeMqttClient)
    def start(self) -> None          # username_pw_set, on_message, connect_async, loop_start, subscribe status au on_connect
    def stop(self) -> None
    def publish(self, state: str, challenge_id: str | None) -> None
        # payload json {"state","ts" (ISO 8601 UTC, Z),"challenge_id"} ; qos=1 ; retain=False
        # succès -> led_publish_total{state,"ok"} + log led_state_published ; exception/rc!=0/non connecté -> {state,"error"} + led_publish_failed ; JAMAIS d'exception propagée
    @property
    def online(self) -> bool | None  # dernier {"online": bool} reçu sur status ; None si jamais reçu
# config.py : mqtt_host: str = "" (MQTT_HOST ; vide => LogLedNotifier), mqtt_port: int = 1883, mqtt_username: str = "auth", mqtt_password: str = "" (read_secret optionnel MQTT_AUTH_PASSWORD / _FILE)
# route : GET /api/v1/auth/device -> {"led_online": bool | null}  (LogLedNotifier => null)
# LedNotifier Protocol : + attribut optionnel `online` (getattr(led, "online", None))
```
- [ ] **Step 1: Tests** : payload/topic/QoS ; `ts` ISO ; publish quand le client lève → pas d'exception + métrique error + log `led_publish_failed` ; publish quand déconnecté → error ; message status `{"online":false}` → `online is False` ; JSON invalide ignoré ; `GET /api/v1/auth/device` renvoie la valeur ; settings sans `MQTT_HOST` ⇒ `LogLedNotifier`.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implémenter** (lifespan : `start()` au démarrage, `stop()` à l'arrêt). **Step 4: Run** auth complet → vert.

---

### Task 5: `auth` — API d'administration (habilitations) + bootstrap

**Files:**
- Create: `services/auth/src/auth_service/admin.py`
- Modify: `schemas.py`, `config.py` (`backoffice_bootstrap_token: str = ""` via `read_secret` optionnel `BACKOFFICE_BOOTSTRAP_TOKEN`), `security.py` (`decode_access_token(token, secret) -> dict`), `main.py`
- Test: `services/auth/tests/test_admin.py`

**Consumes:** `FaceIdClient` (T3), `create_access_token(username, secret, role=...)` existant.
**Produces (HTTP) :**
```
Auth : Authorization: Bearer <jwt> ; rôle requis "admin" (401 missing_token/invalid_token, 403 forbidden)
GET    /api/v1/admin/users                       200 [{username, role, enrolled, enrolled_at, enrolled_by}]  (tous les users ; enrolled via face_client.enrollments())
POST   /api/v1/admin/users  {username, password, role}   201 {username, role} | 409 username_taken | 422
PATCH  /api/v1/admin/users/{username} {role}     200 {username, role} | 404 unknown_user | 409 last_admin
PUT    /api/v1/admin/users/{username}/face {poses:{face,gauche,droite}}  200 {enrolled:true, model_version} | 422 enrollment_rejected (details relayés) | 404 | 503 face_service_unavailable
DELETE /api/v1/admin/users/{username}/face      204 | 404 not_enrolled | 409 last_admin
GET    /api/v1/admin/users/{username}/face/photos 200 {photos:{...}} | 404
GET    /api/v1/auth/bootstrap                    200 {required: bool}   (required ⇔ aucun user role=admin enrôlé ET token configuré)
POST   /api/v1/auth/bootstrap {token, username, password, poses}  201 {username, role:"admin"} | 403 bootstrap_denied (token faux / non requis) | 422 enrollment_rejected
```
Règles : `last_admin` = l'opération retirerait le dernier admin **enrôlé**. Création sans compte bancaire. Mot de passe : mêmes règles que `RegisterRequest` (8–72 octets), username `^[A-Za-z0-9_.-]{3,32}$`, role ∈ `customer|operator|admin`. Bootstrap : `hmac.compare_digest`, rate-limit `5/minute`, si le user existe on met à jour mot de passe + rôle admin ; si l'enrôlement échoue, rollback de la création. Logs : `admin_user_created`, `admin_role_changed`, `admin_face_enrolled`, `admin_face_revoked`, `backoffice_bootstrap` (champ `user` = cible, message mentionne l'acteur). Rate-limit des routes admin = `backoffice_rate_limit`.

- [ ] **Step 1: Tests** (`FakeFaceClient` en mémoire injecté via `create_app(face_client=...)`) : RBAC (sans token 401, operator 403, admin 200), création + liste, doublon 409, rôle invalide 422, changement de rôle + log, garde dernier admin (PATCH et DELETE), enrôlement relayé avec `enrolled_by == sub`, rejet 422 avec details, photos, bootstrap requis/non requis, token faux 403, bootstrap OK crée admin enrôlé puis `required=false`, bootstrap avec enrôlement rejeté ⇒ pas d'utilisateur créé, events ⊂ RESERVED_EVENTS, pas de mot de passe dans les logs.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implémenter.** **Step 4: Run** auth complet → vert.
- [ ] **Step 5: Docs auth** : `services/auth/README.md` + `CAHIER-DES-CHARGES.md` (routes §3, critères d'acceptation ajoutés pour T3–T5, variables `BACKOFFICE_*`, `MQTT_*`, `FACE_*`).

---

### Task 6: Back-office — thème du front + clients API v2

**Files:**
- Modify: `services/backoffice/package.json` (+ `@fontsource-variable/instrument-sans`, `@fontsource/jetbrains-mono` mêmes versions que `services/front/package.json`), `src/index.css` (copie des tokens/utilities du front + `--color-led-green/red`), `src/main.tsx`
- Create: `src/components/Brand.tsx` (copie du `Brand` du front, avec `src/assets/logo-mark.png` copié depuis `services/front/src/assets/logo-mark.png` s'il existe, sinon lettre « R »), `src/api/http.ts`, `src/api/admin.ts`, `src/lib/pose.ts`, `src/lib/session.ts`
- Modify: `src/api/auth.ts`
- Test: `src/api/auth.test.ts`, `src/api/admin.test.ts`, `src/lib/pose.test.ts`

**Produces (TS) :**
```ts
// api/http.ts
export class ApiError extends Error { status: number; code: string; retryAfter?: number; details?: {pose:string;reason:string}[] }
export async function request<T>(path: string, init: { method?: string; body?: unknown; token?: string }): Promise<T>
// api/auth.ts
export type Pose = 'face' | 'gauche' | 'droite'
export interface IdentifyResult { challenge_id: string; step: 'face'|'password'; expires_in: number; camera: boolean; poses: Pose[] }
export interface FaceFrame { pose: Pose; image_b64: string }
export interface FaceResult { recognized: boolean; step: 'password'|'identify'; attempts_left: number; cooldown: number }
export interface TokenResult { access_token: string; token_type: string; expires_in: number; role: string }
export const identify, verifyFace(challenge_id, frames: FaceFrame[]), submitPassword, deviceStatus(): Promise<{led_online: boolean|null}>,
             bootstrapStatus(): Promise<{required:boolean}>, bootstrap(body: {token,username,password,poses: Record<Pose,string>})
export { ApiError as AuthError }   // compat
// api/admin.ts
export interface AgentRow { username: string; role: 'customer'|'operator'|'admin'; enrolled: boolean; enrolled_at: string|null; enrolled_by: string|null }
export const listUsers(token), createUser(token, {username,password,role}), setRole(token, username, role),
             enrollFace(token, username, poses: Record<Pose,string>), revokeFace(token, username), facePhotos(token, username)
// lib/pose.ts  (miroir exact de face_id/poses.py)
export const SEUIL_FACE = 0.10, SEUIL_PROFIL = 0.15
export function rotationFromPoints(jawLeftX: number, jawRightX: number, noseXs: number[]): number | null
export function poseFromRotation(r: number | null): Pose | null
export const POSE_LABELS: Record<Pose,string> = { face: 'Face', gauche: 'Profil gauche', droite: 'Profil droit' }
// lib/session.ts : jeton en mémoire uniquement (pas de storage) : getSession/setSession/clearSession + decodeRole
```
- [ ] **Step 1: Tests** api (fetch mocké : corps envoyés, `Retry-After`, `details` d'enrôlement, Bearer) + pose.ts (mêmes cas que `test_poses.py`).
- [ ] **Step 2: Run** `npx vitest run` → FAIL. **Step 3: Implémenter** (npm install des fontsource). **Step 4: Run** vitest + tsc + eslint verts (les tests LoginPage existants peuvent casser : ils sont réécrits en T8 — ne pas les supprimer, les marquer `describe.skip` temporairement avec un commentaire `// réécrit en T8`).

---

### Task 7: `FaceScanner` — étape de scan sci-fi + détecteur de pose MediaPipe

**Files:**
- Create: `src/vision/detector.ts`, `src/vision/mediapipe.ts`, `src/components/scanner/FaceScanner.tsx`, `src/components/scanner/scanner.css`, `src/components/scanner/HudOverlay.tsx`, `src/components/scanner/useHoldTimer.ts`
- Create: `scripts/fetch-face-model.mjs` (télécharge `face_landmarker.task` vers `public/models/` avec vérif sha256 ; copie `node_modules/@mediapipe/tasks-vision/wasm/*` vers `public/mediapipe/`), `package.json` scripts `"prepare:vision": "node scripts/fetch-face-model.mjs"`, `.gitignore` (`public/models/`, `public/mediapipe/`)
- Modify: `docker/security-headers.conf` (`script-src 'self' 'wasm-unsafe-eval'`), `Dockerfile` (RUN `npm run prepare:vision` avant build), `src/hooks/useCamera.ts` (ajouter `video` getter + capture `maxSide` 640)
- Test: `src/components/scanner/FaceScanner.test.tsx`, `src/components/scanner/useHoldTimer.test.ts`

**Produces:**
```ts
// vision/detector.ts
export interface Landmarks { points: {x:number;y:number}[]; rotation: number | null; faces: number }
export interface PoseDetector { detect(video: HTMLVideoElement, ts: number): Landmarks | null; close(): void }
export type DetectorFactory = () => Promise<PoseDetector>
// vision/mediapipe.ts : export const createMediaPipeDetector: DetectorFactory
//   FilesetResolver.forVisionTasks('/mediapipe') ; FaceLandmarker.createFromOptions({ baseOptions:{ modelAssetPath:'/models/face_landmarker.task', delegate:'GPU' }, runningMode:'VIDEO', numFaces:2 })
//   rotation = rotationFromPoints(lm[234].x, lm[454].x, [lm[1].x, lm[4].x])  (coordonnées image NON miroir)
// FaceScanner.tsx
export interface FaceScannerProps {
  mode: 'verify' | 'enroll'
  poses: Pose[]                         // ordre à capturer
  camera: Camera                        // hook useCamera (start/stop/capture)
  videoRef: RefObject<HTMLVideoElement | null>
  detectorFactory?: DetectorFactory     // défaut createMediaPipeDetector ; tests : faux détecteur
  holdMs?: number                       // défaut 1000
  verdict?: 'idle' | 'analyzing' | 'granted' | 'denied'   // piloté par le parent
  onComplete: (frames: FaceFrame[]) => void
  onCancel?: () => void
}
```
Comportement : démarre la caméra au montage, boucle `requestAnimationFrame` → `detect` → pose courante ; si pose == attendue et 1 seul visage, l'anneau se remplit sur `holdMs` puis capture (`camera.capture()`), flash, passe à la pose suivante ; après la dernière, `onComplete(frames)` et passe en `analyzing`. Si le détecteur ne charge pas (rejet de la factory) → **mode manuel** : bouton « Capturer » avec compte à rebours 3-2-1 par pose. Caméra arrêtée au démontage.
Visuel (dans le cadre `bg-night`, rien hors du scanner) : vidéo miroir (`scale-x-[-1]`) ; canvas des points du maillage (cyan `#5eead4`, 1.2 px, opacité 0.7) ; réticule 4 coins animés ; ligne de balayage verticale (keyframes `scan` 2.4 s) ; grille 24 px à 6 % ; puces `01 FACE · 02 PROFIL G · 03 PROFIL D` (active/validée) ; flèche de consigne animée (`←`/`→`/`●`) ; anneau SVG de maintien (stroke-dashoffset) ; lecture télémétrie mono (`ROT +0.03 · FACES 1 · POSE OK`) ; verdict `analyzing` (anneaux concentriques tournants + « ANALYSE BIOMÉTRIQUE »), `granted` (teinte verte + « IDENTITÉ CONFIRMÉE »), `denied` (teinte rouge + glitch 400 ms + « NON RECONNU »). `@media (prefers-reduced-motion: reduce)` coupe balayage/glitch/rotation. `aria-live="polite"` sur la consigne.
- [ ] **Step 1: Tests** (faux détecteur scripté, `useCamera` mocké, `vi.useFakeTimers` + rAF mocké) : capture auto dans l'ordre demandé après maintien ; pose incorrecte ne capture pas ; 2 visages ne capture pas ; `onComplete` reçoit 3 frames ordonnées ; repli manuel si la factory rejette ; caméra stoppée au démontage ; consigne annoncée en `aria-live`.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implémenter** (`npm i @mediapipe/tasks-vision@0.10.21`). **Step 4: Run** vitest/tsc/eslint verts. **Step 5:** `node scripts/fetch-face-model.mjs` exécuté une fois (sha256 calculé et figé dans le script après 1er téléchargement depuis `https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task`).

---

### Task 8: Back-office — `LoginPage` v2 (thème front, refroidissements, jumeau LED)

**Files:**
- Modify: `src/pages/LoginPage.tsx`, `src/components/LedIndicator.tsx`, `src/lib/led.ts`, `src/App.tsx`
- Create: `src/hooks/useCountdown.ts`, `src/components/DevicePill.tsx`
- Test: `src/pages/LoginPage.test.tsx` (réécrit), `src/lib/led.test.ts`

**Consumes:** T6 API, T7 `FaceScanner`.
Comportement :
- Mise en page = login du front (grille 2 colonnes `[grid-template-columns:repeat(auto-fit,minmax(min(100%,400px),1fr))]`, panneau gauche `bg-night` avec `Brand inverted`, titre « Accès back-office », sous-texte « Authentification renforcée : identifiant, visage, mot de passe. », `DevicePill` (« Module LED en ligne / hors ligne / inconnu ») ; panneau droit blanc avec formulaire `field`/`btn-primary`).
- Phases : `identify` → `scan` (FaceScanner `mode=verify` avec `poses` du serveur, occupe le panneau droit) → `password` → (succès) `granted` 1.5 s puis `onAuthenticated`.
- Visage refusé : verdict `denied`, LED `not_recognized`, **caméra reste allumée** pendant `cooldown` (30 s) avec compte à rebours dans le scanner (« Nouvelle tentative dans 30 s »), puis caméra OFF + identifiant vidé + retour `identify`. Si `attempts_left == 0` → message blocage.
- Mot de passe refusé : LED `auth_fail` (jumeau rouge ×10 = 3 s), champ désactivé 3 s, puis retour `identify` identifiant vidé.
- 429 `locked_out` → écran blocage + compte à rebours 5 min ; 429 `cooldown` → compte à rebours `Retry-After` sur l'écran identifiant.
- `LedIndicator` : reproduit les timings firmware (vert clignotant demi-période 400 ms ; rouge ×10 demi-période 150 ms puis off ; fixes 30 s puis off) via `useLedTimeline(state, startedAt)` dans `lib/led.ts` (fonction pure `ledOutputAt(state, elapsedMs) -> {color, on}` testée).
- `App.tsx` : `bootstrapStatus()` au montage → si `required` afficher `BootstrapPage` (T9 ; avant T9, placeholder) ; sinon login ; session → `HomePage` (T9).
- [ ] **Step 1: Tests** (FaceScanner mocké via `vi.mock('../components/scanner/FaceScanner')` qui appelle `onComplete` sur clic) : ordre imposé (pas de mot de passe avant visage) ; poses du serveur transmises ; visage refusé ⇒ compte à rebours 30 s puis identifiant vidé ; mot de passe refusé ⇒ 3 s puis retour identifiant ; 429 locked ⇒ écran blocage ; succès ⇒ `onAuthenticated` après séquence ; rôle refusé ⇒ message. `led.test.ts` : `ledOutputAt` pour les 5 états (bornes 30 s, 10 clignotements, 3000 ms).
- [ ] **Step 2: Run** → FAIL. **Step 3: Implémenter.** **Step 4: Run** vitest/tsc/eslint verts.

---

### Task 9: Back-office — Habilitations, assistant « Nouvel agent », Initialisation

**Files:**
- Create: `src/pages/HomePage.tsx`, `src/pages/HabilitationsPage.tsx`, `src/components/EnrollWizard.tsx`, `src/pages/BootstrapPage.tsx`, `src/components/PhotoStrip.tsx`
- Modify: `src/App.tsx`
- Test: `src/pages/HabilitationsPage.test.tsx`, `src/components/EnrollWizard.test.tsx`, `src/pages/BootstrapPage.test.tsx`

Comportement (style front : cartes `bg-frame` / `border-line` / `rounded-2xl`, tableau sobre, badges `ok`/`warn`) :
- `HomePage` : en-tête Brand + rôle + déconnexion ; si `admin` → `HabilitationsPage`, sinon carte « Accès opérateur » (lecture seule, pas d'API admin).
- `HabilitationsPage` : tableau (identifiant, rôle `<select>`, statut visage « Enrôlé le … par … » / « Non enrôlé », actions : Voir photos (PhotoStrip), Ré-enrôler, Révoquer avec confirmation). Bouton « Nouvel agent » → `EnrollWizard`. Erreur `last_admin` affichée en clair.
- `EnrollWizard` (étapes) : 1) identifiant, mot de passe (+ confirmation), rôle ; 2) `FaceScanner mode="enroll" poses={['face','gauche','droite']}` ; 3) récapitulatif vignettes (images capturées) + « Valider l'enrôlement » → `createUser` puis `enrollFace` (ré-enrôlement : seulement `enrollFace`) ; rejet 422 ⇒ affiche les `details` par pose (libellés FR : `wrong_pose` « pose incorrecte », `no_face` « aucun visage », `multiple_faces` « plusieurs visages », `inconsistent` « pas la même personne », `invalid_image` « image illisible ») et **reprise des 3 poses** ; succès ⇒ fermeture + rafraîchissement liste.
- `BootstrapPage` : carte « Initialisation du back-office » : token d'initialisation + identifiant + mot de passe → même scanner enroll → `bootstrap()` → message de succès puis login.
- [ ] **Step 1: Tests** : liste rendue ; changement de rôle appelle `setRole` ; révocation avec confirmation ; erreur `last_admin` ; wizard : validation champs, mots de passe différents, scanner mocké → récap → `createUser`+`enrollFace`, rejet 422 affiche détails et revient au scanner ; bootstrap : token faux ⇒ message, OK ⇒ callback.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implémenter.** **Step 4: Run** vitest/tsc/eslint/`npx vite build` verts.
- [ ] **Step 5: Docs** `services/backoffice/README.md` + `CAHIER-DES-CHARGES.md` (parcours, MediaPipe, accès hôte `https://localhost:9443`, checklist recette : caméra, 3 poses, cooldown 30 s, LED).

---

### Task 10: Infra — compose, WAF hôte, Mosquitto, SOPS, Prometheus

**Files:**
- Modify: `infra/compose/docker-compose.yml`, `security/waf/nginx.conf`, `infra/mosquitto/aclfile`, `infra/mosquitto/mosquitto.conf`, `infra/mosquitto/README.md`, `security/sops/secrets.example.env`, `security/sops/README.md`, `infra/prometheus/prometheus.yml` (job `face-id` → `face-id:8006`)
- Create: `infra/mosquitto/docker-entrypoint.sh` (génère `/mosquitto/config/passwd` dans un tmpfs depuis `MQTT_AUTH_PASSWORD` et `MQTT_LED_PASSWORD` via `mosquitto_passwd -b -c`, puis `exec mosquitto -c ...`)
- Test: `infra/tests/` (étendre les tests existants de durcissement compose) + `security/waf/tests/` (routes)

Contenu :
- `auth` env : `FACE_ID_URL: http://face-id:8006`, `FACE_INTERNAL_TOKEN: ${FACE_INTERNAL_TOKEN}`, `MQTT_HOST: mosquitto`, `MQTT_AUTH_PASSWORD: ${MQTT_AUTH_PASSWORD}`, `BACKOFFICE_BOOTSTRAP_TOKEN: ${BACKOFFICE_BOOTSTRAP_TOKEN}` ; `depends_on: [postgres, face-id, mosquitto]`.
- `face-id` : build `context: ../.., dockerfile: services/face-id/Dockerfile`, `networks: [app, data]`, env Postgres + `FACE_INTERNAL_TOKEN`, `FACE_DATA_KEY`, `RECOGNIZER_BACKEND: team`, `read_only`, `tmpfs /tmp`, `mem_limit: 1g`, `cpus: 1.5`, healthcheck `/health`.
- `backoffice` : build `../../services/backoffice`, `networks: [app]`, `read_only`, `tmpfs /tmp`, `mem_limit: 128m`, healthcheck `/healthz`.
- `mosquitto` : `image: eclipse-mosquitto:2.0.20`, `ports: ["${MQTT_BIND:-192.168.137.1}:1883:1883"]`, `networks: [app]`, volumes conf/acl/entrypoint en `:ro`, `tmpfs: /mosquitto/config/run`, `read_only`, `user: "1883:1883"`, healthcheck `mosquitto_sub ... -C 1 -W 3 -t '$$SYS/broker/uptime'` avec creds auth.
- `waf` : `ports` + `"127.0.0.1:9443:9443"` ; `depends_on` + `backoffice`.
- WAF `nginx.conf` : `upstream backoffice_app { server backoffice:8080; }` ; serveur public : `location ^~ /api/v1/auth/ { return 404; }` et `location ^~ /api/v1/admin/ { return 404; }` ; nouveau `server { listen 9443 ssl; http2 on; server_name _; ssl_* identiques ; if ($blocked_source) {return 403;} ; mêmes en-têtes ; client_max_body_size 4m; location = /healthz ; location / → backoffice_app ; location /api/v1/auth/ → auth_api ; location /api/v1/admin/ → auth_api (X-Forwarded-For $remote_addr) }`.
- `aclfile` : `user auth` + `topic read resilience/led/status`.
- `secrets.example.env` : `FACE_INTERNAL_TOKEN=change-me-face-internal-token-32c`, `FACE_DATA_KEY=<base64 32 octets factice, ex. généré par python -c "import os,base64;print(base64.b64encode(os.urandom(32)).decode())">` (valeur factice explicite), `MQTT_AUTH_PASSWORD=change-me-mqtt-auth`, `MQTT_LED_PASSWORD=change-me-mqtt-led`, `BACKOFFICE_BOOTSTRAP_TOKEN=change-me-bootstrap-token`, `MQTT_BIND=192.168.137.1`.
- [ ] **Step 1: Tests** statiques (lecture YAML/nginx.conf) : services `face-id`, `backoffice`, `mosquitto` durcis (cap_drop ALL, no-new-privileges, read_only, healthcheck) ; aucun `ports` sauf waf et mosquitto ; port 9443 publié sur `127.0.0.1` uniquement ; mosquitto non publié sur `0.0.0.0` ; nginx : `/api/v1/auth/` absent du serveur public (404) et présent sur 9443 ; ACL : auth lit status.
- [ ] **Step 2: Run** `$PY -m pytest -q -p no:cacheprovider infra/tests security/waf/tests` (depuis la racine) → FAIL puis implémenter → vert. (Installer `pyyaml` dans le venv si absent.)
- [ ] **Step 3: Docs** mosquitto README (passwd généré au démarrage), sops README.

---

### Task 11: Documentation transverse

**Files:** `docs/contracts.md` §5 (API face-id v2, API auth v2 + admin + bootstrap + device, données §5.4 photos chiffrées, refroidissements), `docs/adr/0007-acces-hote-vivacite-poses-photos-chiffrees.md`, `docs/consigne-additionnelle-1.md` (§5.1 refroidissements, §6.3–6.6, §7 RGPD amendé, §9 modèle équipe), `docs/consigne-additionnelle-1-roadmap.md` (L1, L3-4, L3-5, L5, L6, L7, L8-2 → statuts + preuves), `ROADMAP.md` (ligne consigne), `docs/ebios-rm.md` (risque spoof réduit par vivacité, photos chiffrées), `docs/pca-pra.md` (perte clé `FACE_DATA_KEY` ⇒ réenrôlement).
- [ ] **Step 1:** Rédiger. **Step 2:** `cd libs/python/resilience_common && $PY -m pytest -q -p no:cacheprovider` vert (cohérence events/contrat).

---

## Exécution & ordre

Flux parallélisables (répertoires disjoints) après T1 : **A** T2 (face-id) · **B** T3→T4→T5 (auth) · **C** T6→T7→T8→T9 (backoffice) · **D** T10 (infra). Puis T11. Vérification finale : toutes les suites (auth, face-id, resilience_db, resilience_common, payment-api non régressé, backoffice, infra/waf tests) vertes + revue de code.
