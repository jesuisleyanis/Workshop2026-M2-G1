# Cahier des charges — `services/face-id`

> Composant de la **Consigne Additionnelle 1** (cadrage : [`docs/consigne-additionnelle-1.md`](../../docs/consigne-additionnelle-1.md), lot **L1**).

## 1. Rôle

**IA légère de reconnaissance de visage** du PC Hôte. Réalise la **vérification 1:1** (l'identifiant saisi correspond-il au visage présenté ?) qui conditionne, dans le back-office durci, le déblocage de la saisie du mot de passe. Porte aussi l'**enrôlement** des habilitations biométriques (gestion des visages des opérateurs/admins).

- Port interne **8006**, réseaux Docker **`app`** (appelé par `auth`) + **`data`** (table `face_enrollments`). Nom de service Compose : **`face-id`**. **Jamais exposé** : seul le WAF l'est ; `/verify` n'est appelé que par `auth`.

## 2. Exigences couvertes

| Réf. | Exigence | Comment |
|---|---|---|
| **CA2** | IA légère de reconnaissance de visage (1:1) | Abstraction `Recognizer` + backend InsightFace `buffalo_s` (ONNX CPU) ; stub déterministe pour les tests |
| **CA5** | Gestion des habilitations (enrôlement) | `POST/DELETE /enroll`, `GET /enrollments` (token interne) |
| **R7/R12** | Observabilité / SOC | Logs JSON contrat §1 (`face_verify_*`, `face_enrolled`, `face_enrollment_revoked`) + métriques §2 |
| **R13/R14** | Secrets / durcissement | `FACE_INTERNAL_TOKEN` via SOPS ; image slim non-root, `read_only`, healthcheck |
| **RGPD** | Donnée biométrique sensible | **Embedding seul** persisté (jamais l'image) ; liste sans biométrie ; droit à l'effacement (`DELETE`) |

## 3. Interfaces (détail des formats : [`docs/contracts.md §5.1`](../../docs/contracts.md#5-consigne-additionnelle-1--authentification-renforcée-du-back-office))

| Méthode & chemin | Auth | Description |
|---|---|---|
| `POST /api/v1/verify` | réseau interne (appelé par `auth`) | `{username, image_b64}` → `{match, score, threshold, model_version}`. Identifiant inconnu/non enrôlé ⇒ `nomatch` (anti-énumération). |
| `POST /api/v1/enroll` | `X-Internal-Token` | `{username, images_b64[], enrolled_by}` → `{enrolled, quality, model_version}`. `404 unknown_user` si l'identifiant n'existe pas. |
| `DELETE /api/v1/enroll/{username}` | `X-Internal-Token` | `204` ; `404 not_enrolled`. |
| `GET /api/v1/enrollments` | `X-Internal-Token` | `[{username, enrolled_at, enrolled_by, model_version}]` — **aucune biométrie**. |
| `GET /health` · `GET /ready` · `GET /metrics` | — | `/ready` = recognizer chargé + DB joignable. |

### Consommées
- **PostgreSQL** (`postgres:5432/resilience`, réseau `data`) : tables `users`, `face_enrollments` (`libs/python/resilience_db`).
- **Secrets (SOPS)** : `FACE_INTERNAL_TOKEN`, `POSTGRES_PASSWORD`. Variantes `*_FILE`.
- **Appelant** : `auth` (étape visage) + back-office (enrôlement, via `auth`), réseau `app`.

## 4. Sécurité & RGPD

- **Embedding uniquement.** Aucune image n'est écrite sur disque ni renvoyée. La table stocke un vecteur float32 (`BYTEA`). Chiffrement au repos de la colonne recommandé (porté en risque résiduel).
- **Anti-énumération :** `verify` d'un identifiant inconnu renvoie `nomatch` (200), pas `404`.
- **Pas de bypass :** `face-id` ne délivre aucun jeton ni session ; il répond seulement `match`/`nomatch`. La décision d'accès reste dans `auth` (facteur ajouté au mot de passe + rôle).
- **Token interne** comparé en temps constant (`hmac.compare_digest`) ; enroll/révoque/list protégés.
- **Garde modèle :** un embedding enrôlé avec un autre `model_version` que le recognizer courant est traité comme `nomatch` (comparaison invalide évitée) ; réenrôlement requis après changement de modèle.
- **Conteneur :** slim, non-root (uid 10001), `read_only`, `cap_drop: ALL`, healthcheck, docs OpenAPI désactivées.

## 5. Critères d'acceptation (chacun couvert par un test)

| # | Critère | Test |
|---|---|---|
| F1 | Enrôlement puis `verify` du même visage ⇒ `match` | `test_enroll_then_verify_matches_same_face` |
| F2 | Visage différent ⇒ `nomatch` (score < seuil) | `test_verify_rejects_a_different_face` |
| F3 | Identifiant inconnu ⇒ `nomatch` 200 (anti-énumération), pas 404 | `test_verify_unknown_user_is_nomatch_not_404` |
| F4 | `enroll`/`delete`/`enrollments` exigent le token interne | `test_enroll_requires_internal_token` |
| F5 | Enrôlement d'un identifiant inconnu ⇒ `404` | `test_enroll_unknown_user_is_404` |
| F6 | La liste ne renvoie **aucune** donnée biométrique | `test_enrollments_list_exposes_no_biometric_data` |
| F7 | Révocation efface l'enrôlement (verify repasse `nomatch`) | `test_revoke_deletes_enrollment` |
| F8 | `image_b64` invalide ⇒ `422` | `test_verify_rejects_invalid_base64` |
| F9 | Tous les `event` émis ∈ contrat §1 | `test_all_emitted_events_belong_to_the_contract` |

## 6. Hors périmètre / limites assumées

- Reconnaissance **1:1** (vérification), pas d'identification 1:N.
- **Pas de liveness / anti-spoofing** en v1 (photo-d'une-photo) — porté en risque résiduel + amélioration optionnelle (cadrage §7).
- Le **StubRecognizer** sert les tests (plumbing déterministe) ; la **qualité réelle** de reconnaissance et le **seuil** sont calibrés en recette avec `RECOGNIZER_BACKEND=insightface`.
- Un seul enrôlement par utilisateur (unicité DB) ; un réenrôlement remplace l'embedding.
