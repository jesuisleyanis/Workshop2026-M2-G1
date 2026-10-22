# Cahier des charges — `services/backoffice`

> Composant de la **Consigne Additionnelle 1** (cadrage : [`docs/consigne-additionnelle-1.md`](../../docs/consigne-additionnelle-1.md), lot **L3** ; décision [ADR 0004](../../docs/adr/0004-backoffice-app-dediee.md)).
> **Statut : implémenté** (login à étapes v2, habilitations, assistant d'enrôlement, initialisation) ; reste la **recette matérielle** sur le PC Hôte (§7). Le backend (auth à étapes, face-id, LED) est spécifié dans le cadrage et indépendant de cette UI.

## 1. Rôle

**Back-office privilégié** du SI : la surface d'**administration** réservée aux rôles `operator`/`admin`. Il porte (1) le **login à étapes durci** (identifiant → visage → mot de passe), (2) la **gestion complète des habilitations** (rôles + enrôlement/révocation des visages) et (3) l'**initialisation** du premier administrateur. Application React + Vite + TypeScript + Tailwind (même stack et même thème que `services/front`), servie **derrière le WAF**.

- Port interne **8080** (nginx), réseau **`edge`** (via WAF) + appels API vers `auth`. Jamais exposé directement.
- **Accès depuis le PC Hôte uniquement : `https://localhost:9443`.** Le listener WAF `127.0.0.1:9443` sert le back-office, `/api/v1/auth/*` et `/api/v1/admin/*` ; ces routes ne sont pas servies sur 80/443. La caméra lue par `getUserMedia` est donc nécessairement celle de l'hôte.

## 2. Exigences couvertes

| Réf. | Exigence | Comment |
|---|---|---|
| **CA1** | Saisie identifiant puis caméra USB (PC Hôte) | `getUserMedia()` dans le navigateur de l'hôte ([ADR 0005](../../docs/adr/0005-camera-navigateur-hote.md)) |
| **CA3** | Visage reconnu ⇒ mot de passe ; sinon identifiant vidé + caméra OFF | machine à états UI alignée sur `auth` (contrat §5.2) |
| **CA5** | Gestion complète des habilitations | écran rôles + enrôlement/révocation (via `auth` → `face-id`) |
| **CA7** | Témoin visuel aligné sur la LED | jumeau LED : même séquence et mêmes timings que le firmware |
| **R11/R14** | Derrière WAF, durci | nginx non-root, `read_only` + tmpfs (parité `front`) |

## 3. Écrans et parcours

1. **Connexion à étapes** (3 poses, refroidissements, LED jumeau).
   (a) identifiant → `POST /auth/identify` → caméra ON ;
   (b) **trois poses** (`face`, `gauche`, `droite`, ordre fourni par le serveur) capturées automatiquement après 1 s de maintien → `POST /auth/face` → reconnu : champ mot de passe ; non reconnu : LED rouge fixe, caméra ON pendant le **refroidissement de 30 s** (`BACKOFFICE_REJECT_COOLDOWN`), puis caméra OFF et identifiant vidé ;
   (c) mot de passe → `POST /auth/password` → « accès autorisé » (LED verte 30 s) ; mot de passe refusé : LED **rouge ×10 en 3 s**, champ gelé 3 s (`BACKOFFICE_FAIL_COOLDOWN`) ;
   (d) **2 échecs ⇒ blocage 5 min** (`429 locked_out`, écran de blocage avec décompte).
   Le **jumeau LED** (panneau gauche) rejoue la séquence du firmware aux mêmes timings ; une pastille indique si le module ESP8266 est en ligne.
2. **Habilitations** (rôle `admin`). Tableau des agents : identifiant, rôle modifiable, statut visage (« Enrôlé le … par … » / « Réenrôlement requis » si l'enrôlement est périmé — `stale` — / « Non enrôlé »), actions **Voir photos** (3 vignettes), **Ré-enrôler**, **Révoquer** (avec confirmation). Le refus du serveur `last_admin` (dernier administrateur) est affiché en clair. Un opérateur n'a qu'une carte « Accès opérateur » en lecture seule.
3. **Assistant « Nouvel agent »** (depuis Habilitations). Étape 1 : identifiant (`^[A-Za-z0-9_.-]{3,32}$`), mot de passe (8–72 octets UTF-8) + confirmation, rôle (`customer`/`operator`/`admin`). Étape 2 : scanner d'enrôlement sur les trois poses. Étape 3 : récapitulatif des vignettes capturées, puis « Valider l'enrôlement » (`createUser` puis `enrollFace` ; ré-enrôlement : `enrollFace` seul). Un **rejet 422** du serveur affiche le motif par pose (pose incorrecte, aucun visage, plusieurs visages, pas la même personne, image illisible) et **fait refaire les trois poses**, sans recréer le compte.
4. **Initialisation** (aucun administrateur, `GET /auth/bootstrap` → `required`). Jeton d'initialisation + identifiant + mot de passe, même scanner d'enrôlement, `POST /auth/bootstrap` ; succès ⇒ message puis retour au login ; jeton refusé (`403 bootstrap_denied`) ⇒ retour au formulaire.

## 4. Sécurité

- Caméra active **uniquement** pendant la capture (login, refroidissement après refus, enrôlement), coupée ensuite (`MediaStreamTrack.stop()`).
- Les trames JPEG sont transmises à `auth` via HTTPS (WAF) ; côté client elles ne vivent en mémoire que le temps du scan et du récapitulatif. Aucune image, aucun jeton, aucun mot de passe dans le stockage navigateur (session en mémoire) ni dans les logs.
- L'accès au back-office exige un **rôle privilégié** (vérifié côté `auth`, claim JWT) : l'UI ne fait pas foi (`403` affiché si un non-admin atteint l'API d'administration).
- **MediaPipe auto-hébergé** : modèle `face_landmarker` et runtime wasm servis en same-origin (`/models`, `/mediapipe`), préparés par `npm run prepare:vision` (empreinte sha256 vérifiée) ; aucun CDN, CSP `script-src 'self' 'wasm-unsafe-eval'`.
- Aucun secret dans le bundle (servi derrière le WAF) — cf. `front`.

## 5. Critères d'acceptation (tests Vitest — `getUserMedia` et FaceScanner mockés)

| # | Critère |
|---|---|
| B1 | L'ordre des étapes est imposé : pas de champ mot de passe avant « reconnu ». |
| B2 | Visage rejeté ⇒ caméra ON pendant 30 s puis identifiant vidé + caméra arrêtée + message. |
| B3 | Blocage (`429`) ⇒ écran de blocage avec décompte. |
| B4 | Enrôlement : capture 3 poses → récapitulatif → `createUser` + `enrollFace` ; rejet 422 ⇒ détails par pose et reprise des 3 poses ; ré-enrôlement ⇒ `enrollFace` seul. |
| B5 | Le témoin d'état reflète les 5 états (idle/recognized/auth_ok/auth_fail/not_recognized). |
| B6 | Habilitations : liste, changement de rôle (`setRole`), révocation avec confirmation, erreur `last_admin` en clair, gating `admin`. |
| B7 | Initialisation : champs validés, jeton faux ⇒ message, succès ⇒ retour au login. |

## 6. Hors périmètre

- Pas de refonte des écrans métier (ils restent dans `front`).
- Option B (greffer sur `front`) : si retenue, ce périmètre devient un module de `front` ; le backend est inchangé.

## 7. Checklist de recette (PC Hôte, matériel réel)

À dérouler sur `https://localhost:9443` avec la caméra USB de l'hôte et le module LED.

- [ ] Caméra USB de l'hôte détectée, aperçu affiché, voyant éteint hors scan.
- [ ] 3 poses (face, gauche, droite) capturées automatiquement au login et à l'enrôlement.
- [ ] Visage refusé : **refroidissement 30 s** (LED rouge fixe, caméra ON), puis identifiant vidé.
- [ ] Mot de passe refusé : LED **rouge ×10 en 3 s**.
- [ ] Accès autorisé : LED **verte 30 s**.
- [ ] 2 échecs : **blocage 5 min**.
- [ ] **LED physique synchronisée** avec le jumeau LED de l'écran.
- [ ] **Calibrage des marges de capture** `0.07` (face) / `0.22` (profil), `src/components/scanner/captureMargins.ts` : comparer la rotation client (MediaPipe) à la rotation serveur (`face-id`) et ajuster si `wrong_pose` à l'enrôlement.
- [ ] Initialisation d'un environnement vierge, ajout d'un agent, ré-enrôlement, révocation, refus du `last_admin`.
