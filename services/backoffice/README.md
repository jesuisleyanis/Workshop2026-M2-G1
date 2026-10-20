# backoffice — back-office durci (consigne additionnelle 1)

Application React + Vite + TypeScript + Tailwind, réservée aux rôles `operator`/`admin`, servie
derrière le WAF. Porte le **login à étapes** (identifiant → visage → mot de passe), l'écran
**Habilitations** (rôles + visages), l'assistant **Nouvel agent** et l'**initialisation** du premier
administrateur. Voir le [cahier des charges](CAHIER-DES-CHARGES.md) et le
[cadrage](../../docs/consigne-additionnelle-1.md).

> **Accès : PC Hôte uniquement, `https://localhost:9443`.** Le WAF ne sert le back-office et
> `/api/v1/auth/*` + `/api/v1/admin/*` que sur ce listener lié à `127.0.0.1` (404 sur 80/443) :
> la caméra utilisée est donc forcément celle de l'hôte.

## Lancer / tester

```bash
npm install
npm run prepare:vision   # modèle face_landmarker (sha256 vérifié) + runtime wasm MediaPipe dans public/
npm run dev        # http://localhost:5174 (proxy /api -> auth, DEV_AUTH_TARGET)
npm test           # Vitest (getUserMedia mocké — aucun matériel requis)
npm run build      # tsc --noEmit + build de production (nginx statique via Docker)
npm run lint
```

## Flux de connexion (contrat §5.2)

```
identifiant ──/auth/identify──► caméra ON (getUserMedia, caméra du PC Hôte, ADR 0005)
   3 poses ──/auth/face───────► reconnu ? ─oui─► champ mot de passe (caméra OFF)
                                          └non─► LED rouge fixe, caméra ON 30 s (décompte),
                                                 puis caméra OFF + identifiant vidé
   mot de passe ─/auth/password► OK (rôle privilégié) ─► « accès autorisé » 1,5 s ─► back-office
                              └401─► LED rouge ×10, champ gelé 3 s, retour à l'identifiant
```

- La caméra est **active seulement pendant le scan** (et le refroidissement de 30 s qui suit un
  refus) ; elle est coupée dès qu'on en sort (vie privée).
- L'ordre des étapes est **imposé par le serveur** (`auth`) ; l'UI en est le reflet : `429
  locked_out` → écran de blocage avec décompte 5 min, `429 cooldown` → décompte `Retry-After` sur
  l'identifiant, dernier essai visage raté → blocage après le refroidissement.
- **Jumeau LED** (panneau gauche) : rejoue la séquence du firmware aux mêmes timings
  (`lib/led.ts`, `ledOutputAt`) ; la pastille indique si le module ESP8266 est en ligne
  (`GET /auth/device`).
- Mise en page identique au login du front (panneau nuit + formulaire blanc) ; le FaceScanner
  est le seul élément « sci-fi ». Au montage, `App` interroge `GET /auth/bootstrap` (premier
  admin à créer ?) avant de présenter le login.
- Aucune image n'est conservée côté client ; la trame JPEG base64 part vers `auth`.

## Scanner de visage (`src/components/scanner/FaceScanner.tsx`)

- Suivi de pose **dans le navigateur** (MediaPipe Face Landmarker, **auto-hébergé** : chargé à la
  demande depuis `/models` et `/mediapipe`, aucun CDN) : chaque pose demandée (`face`, `gauche`,
  `droite`) est capturée automatiquement après 1 s de maintien, un seul visage dans le champ.
  Repli **manuel** (bouton + 3-2-1) si le détecteur ne charge pas.
- Rotation calculée sur l'image **non miroir** (même formule que `face-id`) ; seul l'aperçu est
  affiché en miroir, d'où la flèche « gauche » vers la gauche de l'écran.
- Assets servis en same-origin (`/models`, `/mediapipe`, ignorés par git) : à préparer une fois avec
  **`npm run prepare:vision`** (aussi lancé par le Dockerfile) ; CSP `script-src 'self' 'wasm-unsafe-eval'`.
- Marges de capture (`scanner/captureMargins.ts`) : face `|r| ≤ 0.07`, profil `|r| ≥ 0.22`, plus
  strictes que les seuils du contrat (0.10 / 0.15) pour absorber l'écart de mesure MediaPipe / dlib.
- Captures JPEG ≤ 640 px envoyées telles quelles ; rien n'est conservé côté client.

## Habilitations, assistant « Nouvel agent », initialisation

Écrans réservés au rôle `admin` (claim du jeton, utilisé pour choisir l'écran seulement : le serveur
reste l'autorité, `403` sinon, affiché en clair). Un opérateur voit la carte « Accès opérateur »
(lecture seule, aucun appel à l'API d'administration).

- **Habilitations** (`pages/HabilitationsPage.tsx`) : tableau des agents (identifiant, rôle en
  `<select>`, statut visage « Enrôlé le … par … » / « Non enrôlé »). Actions : **Voir photos**
  (`PhotoStrip`, trois vignettes servies par `auth`), **Ré-enrôler**, **Révoquer** (avec
  confirmation). `409 last_admin` (dernier administrateur) est affiché en clair ; `401` ramène au login.
- **Assistant « Nouvel agent »** (`components/EnrollWizard.tsx`) : 1) identifiant, mot de passe
  (+ confirmation), rôle — règles miroir du serveur (identifiant `^[A-Za-z0-9_.-]{3,32}$`, mot de
  passe 8–72 octets UTF-8) ; 2) `FaceScanner mode="enroll"` sur les poses `face`, `gauche`, `droite` ;
  3) récapitulatif des vignettes puis « Valider l'enrôlement » (`createUser` puis `enrollFace`). Le
  compte n'est créé qu'à la validation ; un **rejet 422** affiche le motif par pose (pose incorrecte,
  aucun visage, plusieurs visages, pas la même personne, image illisible) et **refait les 3 poses**
  sans recréer le compte. Le ré-enrôlement saute l'étape 1 (`enrollFace` seul).
- **Initialisation** (`pages/BootstrapPage.tsx`) : affichée quand `GET /auth/bootstrap` indique
  qu'aucun admin n'existe. Jeton d'initialisation + identifiant + mot de passe → même scanner →
  `POST /auth/bootstrap` → message de succès puis connexion. Jeton refusé (`403 bootstrap_denied`)
  → retour au formulaire.
- Les photos capturées ne vivent en mémoire que le temps du récapitulatif ; la caméra est coupée dès
  que le scanner est démonté.

## Recette sur le PC Hôte (matériel réel)

Non automatisable (caméra, ESP8266) : à dérouler à la main sur `https://localhost:9443`.

- [ ] Caméra USB de l'hôte détectée, aperçu affiché, voyant de la caméra éteint hors scan.
- [ ] 3 poses (face, gauche, droite) capturées automatiquement au login et à l'enrôlement.
- [ ] Visage refusé : LED rouge fixe, caméra ON, **refroidissement 30 s**, puis identifiant vidé.
- [ ] Mot de passe refusé : LED **rouge ×10 en 3 s**, champ gelé 3 s.
- [ ] Accès autorisé : LED **verte 30 s**.
- [ ] 2 échecs : **blocage 5 min** (écran de blocage + décompte).
- [ ] **LED physique synchronisée** avec le jumeau LED de l'écran (mêmes états, mêmes timings).
- [ ] **Calibrage des marges de capture** (`captureMargins.ts` : face `|r| ≤ 0.07`, profil
      `|r| ≥ 0.22`) : comparer la rotation du HUD à celle de `face-id` sur la caméra réelle ; ajuster
      si des `wrong_pose` apparaissent à l'enrôlement.
- [ ] Environnement vierge : initialisation, ajout d'un agent, ré-enrôlement, révocation, refus du
      `last_admin`.

## État

- ✅ Login à étapes v2 (thème front, FaceScanner, refroidissements 30 s / 3 s, blocage 5 min, jumeau LED aux timings firmware).
- ✅ Habilitations, assistant « Nouvel agent », ré-enrôlement, révocation, initialisation du premier admin — **131 tests Vitest** (`npm test`).
- 🟨 Recette matérielle sur le PC Hôte (checklist ci-dessus).

## Place dans le flux

Consommateur de `auth` (étapes et administration) ; l'enrôlement passe par `auth → face-id`. Ne
manipule aucun secret et ne fait pas foi pour les habilitations (décision côté `auth`, claim `role`
du JWT).
