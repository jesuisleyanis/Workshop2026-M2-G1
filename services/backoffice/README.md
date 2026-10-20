# backoffice — back-office durci (consigne additionnelle 1)

Application React + Vite + TypeScript + Tailwind, réservée aux rôles `operator`/`admin`, servie
derrière le WAF. Porte le **login à étapes** (identifiant → visage → mot de passe) et, à venir,
l'écran d'habilitations. Voir le [cahier des charges](CAHIER-DES-CHARGES.md) et le
[cadrage](../../docs/consigne-additionnelle-1.md).

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

- Suivi de pose **dans le navigateur** (MediaPipe Face Landmarker, chargé à la demande) : chaque
  pose demandée par le serveur (`face`, `gauche`, `droite`) est capturée automatiquement après
  1 s de maintien, un seul visage dans le champ. Repli **manuel** (bouton + 3-2-1) si le
  détecteur ne charge pas.
- Rotation calculée sur l'image **non miroir** (même formule que `face-id`) ; seul l'aperçu est
  affiché en miroir, d'où la flèche « gauche » vers la gauche de l'écran.
- Assets servis en same-origin (`/models`, `/mediapipe`, ignorés par git, préparés par
  `npm run prepare:vision`, aussi lancé par le Dockerfile) ; CSP `script-src 'self' 'wasm-unsafe-eval'`.
- Captures JPEG ≤ 640 px envoyées telles quelles ; rien n'est conservé côté client.

## État

- ✅ Login à étapes v2 (thème front, FaceScanner, refroidissements 30 s / 3 s, blocage 5 min, jumeau LED aux timings firmware) — **98 tests Vitest** (`npm test`).
- 🟨 Écran **habilitations** (enrôlement des visages + rôles) — lot **L6** (placeholder actuel).

## Place dans le flux

Consommateur de `auth` (étapes) ; pour l'enrôlement (L6), de `auth → face-id`. Ne manipule aucun
secret et ne fait pas foi pour les habilitations (décision côté `auth`, claim `role` du JWT).
