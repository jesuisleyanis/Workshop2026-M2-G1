# Cahier des charges — `services/face-id`

> Composant de la **Consigne Additionnelle 1** (cadrage : [`docs/consigne-additionnelle-1.md`](../../docs/consigne-additionnelle-1.md), lot **L1**). Version **v2** : enrôlement 3 poses, vérification de séquence, biométrie chiffrée au repos.

## 1. Rôle

**IA légère de reconnaissance de visage** du PC Hôte. Réalise la **vérification 1:1** (l'identifiant saisi correspond-il au visage présenté ?) sur une **séquence de 3 poses** (face, gauche, droite) qui conditionne, dans le back-office durci, le déblocage de la saisie du mot de passe. Porte aussi l'**enrôlement** des habilitations biométriques (gestion des visages des opérateurs/admins).

- Port interne **8006**, réseaux Docker **`app`** (appelé par `auth`) + **`data`** (table `face_enrollments`). Nom de service Compose : **`face-id`**. **Jamais exposé** : seul le WAF l'est ; `/verify` n'est appelé que par `auth`.

## 2. Exigences couvertes

| Réf. | Exigence | Comment |
|---|---|---|
| **CA2** | IA légère de reconnaissance de visage (1:1) | Abstraction `Recognizer` (`analyze` → gabarit + pose, `distance`) ; backend `team` (dlib / `face_recognition`, modèle de l'équipe) ; stub déterministe pour les tests |
| **CA5** | Gestion des habilitations (enrôlement) | `POST/DELETE /enroll`, `GET /enrollments`, `GET /enrollments/{u}/photos` (token interne) |
| **R7/R12** | Observabilité / SOC | Logs JSON contrat §1 (`face_verify_*`, `face_enrolled`, `face_enrollment_rejected`, `face_photos_viewed`, `face_enrollment_revoked`) + métriques §2 |
| **R13/R14** | Secrets / durcissement | `FACE_INTERNAL_TOKEN` et `FACE_DATA_KEY` via SOPS ; image slim non-root, `read_only`, healthcheck |
| **RGPD** | Donnée biométrique sensible | Gabarits **et** vignettes **chiffrés au repos** (AES-256-GCM) ; liste sans biométrie ; consultation des photos **journalisée** ; droit à l'effacement (`DELETE`) |

## 3. Interfaces (détail des formats : [`docs/contracts.md §5.1`](../../docs/contracts.md#5-consigne-additionnelle-1--authentification-renforcée-du-back-office))

Toutes les routes `/api/v1/*` exigent `X-Internal-Token`. Erreurs au format contrat `{"error":{"code","message"}}`.

| Méthode & chemin | Description |
|---|---|
| `POST /api/v1/enroll` | `{username, enrolled_by, poses:{face,gauche,droite}}` → `{enrolled, model_version, poses}`. `422 enrollment_rejected` + `details:[{pose, reason}]` (`no_face`, `multiple_faces`, `wrong_pose`, `inconsistent`, `invalid_image`, `missing`) ; `404 unknown_user`. Tout ou rien. |
| `POST /api/v1/verify` | `{username, frames:[{pose, image_b64}×3]}` (3 poses **distinctes** de `face/gauche/droite`) → `{match, model_version}`. Aucun score ni motif dans la réponse (motif dans les logs). Identifiant inconnu/non enrôlé ⇒ `match:false` (anti-énumération). |
| `DELETE /api/v1/enroll/{username}` | `204` ; `404 not_enrolled`. |
| `GET /api/v1/enrollments` | `[{username, enrolled_at, enrolled_by, model_version, poses}]` — **aucune biométrie**. |
| `GET /api/v1/enrollments/{username}/photos?viewer=<admin>` | `{photos:{face,gauche,droite:<b64 JPEG ≤ 240 px>}}` ; `404` si non enrôlé / ligne v1. Journalise `face_photos_viewed`. |
| `GET /health` · `GET /ready` · `GET /metrics` | `/ready` = recognizer chargé + DB joignable. |

### Règles métier
- **Poses** (clés exactes `face`, `gauche`, `droite`) déduites de la rotation du nez dans la mâchoire : `|rot| ≤ 0,10` face, `rot ≥ 0,15` gauche, `rot ≤ −0,15` droite (zone morte = pose indéterminée).
- **Enrôlement** : par pose, un seul visage, pose détectée = pose attendue ; les gabarits `gauche`/`droite` doivent rester à distance ≤ seuil du gabarit `face` (même personne sur la série).
- **Vérification** : chaque image est comparée au gabarit de **sa** pose (distance euclidienne ≤ 0,6 pour `team`) et la pose détectée doit être la pose demandée. Les 3 images sont évaluées (pas de court-circuit) ; motif ∈ `ok`, `no_face`, `multiple_faces`, `wrong_pose`, `face_mismatch`, `incomplete`.

### Consommées
- **PostgreSQL** (`postgres:5432/resilience`, réseau `data`) : tables `users`, `face_enrollments` (`libs/python/resilience_db`, migration `0003`).
- **Secrets (SOPS)** : `FACE_INTERNAL_TOKEN`, `FACE_DATA_KEY` (base64, 32 octets), `POSTGRES_PASSWORD`. Variantes `*_FILE`.
- **Appelant** : `auth` (étape visage + enrôlement/consultation via le back-office), réseau `app`.

## 4. Sécurité & RGPD

- **Chiffrement au repos.** Gabarits (colonne `embedding`) et vignettes (colonne `photos`) sont scellés en **AES-256-GCM** (`v1 ‖ nonce ‖ chiffré+tag`) avec `FACE_DATA_KEY`. L'AAD (`<username>|templates` / `<username>|photos`) lie chaque blob à son propriétaire : un blob recopié sur une autre ligne ne se déchiffre pas. Aucune image pleine résolution n'est persistée : seules des **vignettes JPEG ≤ 240 px** le sont, pour la validation visuelle par un administrateur.
- **Traçabilité.** Chaque consultation des photos par un administrateur est journalisée (`face_photos_viewed` : compte consulté + administrateur). Aucune image, aucun gabarit, aucune clé ni token n'apparaît dans les logs (test dédié).
- **Anti-énumération :** `verify` d'un identifiant inconnu renvoie `match:false` (200), pas `404`.
- **Anti-rejeu de photo :** la séquence de poses est demandée dans un ordre que l'attaquant ne connaît pas ; une photo fixe échoue sur `wrong_pose`.
- **Pas de bypass :** `face-id` ne délivre aucun jeton ni session ; il répond seulement `match`/`nomatch`. La décision d'accès reste dans `auth`.
- **Token interne** comparé en temps constant (`hmac.compare_digest`) ; toutes les routes métier sont protégées.
- **Garde modèle / lignes v1 :** un enrôlement d'un autre `model_version`, ou une ancienne ligne v1 (gabarit non chiffré, sans photos), est traité comme `match:false` + log `face_verify_error` (**réenrôlement requis**) ; un blob illisible (altéré, mauvaise clé) a le même traitement. Jamais de 500.
- **Perte de clé :** perdre ou changer `FACE_DATA_KEY` rend les enrôlements illisibles ; la procédure est un réenrôlement (la clé est sauvegardée avec les autres secrets SOPS).
- **Conteneur :** slim, non-root (uid 10001), `read_only`, `cap_drop: ALL`, healthcheck, docs OpenAPI désactivées ; dlib compilé dans un étage builder (aucune toolchain dans l'image finale).

## 5. Critères d'acceptation (chacun couvert par un test)

| # | Critère | Test |
|---|---|---|
| F1 | Enrôlement des 3 poses puis `verify` dans un ordre quelconque ⇒ `match` | `test_enroll_three_poses_then_verify_in_random_order_matches` |
| F2 | Autre identité ⇒ `match:false` | `test_verify_rejects_other_identity` |
| F3 | Mauvaise pose dans la séquence ⇒ `match:false` | `test_verify_rejects_wrong_pose_in_sequence` |
| F4 | Exactement 3 poses distinctes sinon `422` | `test_verify_requires_exactly_three_distinct_poses` |
| F5 | Identifiant inconnu ⇒ `match:false` 200 (anti-énumération), pas 404 | `test_unknown_user_verify_is_nomatch_not_404` |
| F6 | Série refusée en bloc avec détail par pose (`422 enrollment_rejected`) | `test_enroll_rejects_whole_series_with_per_pose_details` |
| F7 | Identité incohérente entre poses refusée | `test_enroll_rejects_inconsistent_identity_across_poses` |
| F8 | Enrôlement d'un identifiant inconnu ⇒ `404` | `test_enroll_unknown_user_404` |
| F9 | Gabarits **et** photos chiffrés au repos (préfixe `v1`, pas de clair) | `test_templates_and_photos_are_encrypted_at_rest` |
| F10 | Photos : token requis + consultation journalisée | `test_photos_endpoint_requires_token_and_logs_view` |
| F11 | La liste ne renvoie **aucune** donnée biométrique (+ champ `poses`) | `test_enrollments_list_exposes_no_biometric_data` |
| F12 | Révocation efface l'enrôlement | `test_revoke_deletes_enrollment` |
| F13 | Routes protégées par le token interne | `test_verify_requires_internal_token`, `test_enroll_requires_internal_token` |
| F14 | Autre `model_version` ⇒ `match:false` + log `face_verify_error` | `test_model_version_mismatch_is_nomatch_with_error_log` |
| F15 | Ligne v1 : réenrôlement requis, jamais de plantage | `test_legacy_v1_row_requires_reenrolment_and_never_crashes` |
| F16 | `FACE_DATA_KEY` requise et valide | `test_settings_require_face_data_key` |
| F17 | Aucun log ne contient image, gabarit, clé ou token | `test_logs_never_contain_image_or_embedding` |
| F18 | Tous les `event` émis ∈ contrat §1 | `test_all_emitted_events_belong_to_the_contract` |
| F19 | Vignette Pillow : JPEG, ≤ 240 px, jamais d'agrandissement, non-image refusée | `test_thumbnail_*` (`tests/test_enrollment.py`) |

## 6. Hors périmètre / limites assumées

- Reconnaissance **1:1** (vérification), pas d'identification 1:N.
- **Pas de liveness / anti-spoofing** avancé : la séquence de poses aléatoire est un premier rempart contre la photo fixe, pas contre une vidéo rejouée — porté en risque résiduel (cadrage §7).
- Le **StubRecognizer** sert les tests (plumbing déterministe) ; la **qualité réelle** de reconnaissance et les seuils sont calibrés en recette avec `RECOGNIZER_BACKEND=team`.
- Un seul enrôlement par utilisateur (unicité DB) ; un réenrôlement remplace gabarits et photos.
- L'image Docker `team` n'a pas pu être construite dans l'environnement de développement (pas de démon Docker) : à valider à la première construction sur le PC Hôte.
