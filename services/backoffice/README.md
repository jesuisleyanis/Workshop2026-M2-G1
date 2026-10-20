# backoffice — back-office durci (consigne additionnelle 1)

Application React + Vite + TypeScript + Tailwind, réservée aux rôles `operator`/`admin`, servie
derrière le WAF. Porte le **login à étapes** (identifiant → visage → mot de passe) et, à venir,
l'écran d'habilitations. Voir le [cahier des charges](CAHIER-DES-CHARGES.md) et le
[cadrage](../../docs/consigne-additionnelle-1.md).

## Lancer / tester

```bash
npm install
npm run dev        # http://localhost:5174 (proxy /api -> auth, DEV_AUTH_TARGET)
npm test           # Vitest (getUserMedia mocké — aucun matériel requis)
npm run build      # tsc --noEmit + build de production (nginx statique via Docker)
npm run lint
```

## Flux de connexion (contrat §5.2)

```
identifiant ──/auth/identify──► caméra ON (getUserMedia, caméra du PC Hôte, ADR 0005)
   trame ────/auth/face───────► reconnu ? ─oui─► champ mot de passe (caméra OFF)
                                          └non─► identifiant vidé, caméra OFF, LED rouge
   mot de passe ─/auth/password► OK (rôle privilégié) ─► back-office
```

- La caméra est **active seulement pendant le scan** et coupée dès qu'on en sort (vie privée).
- L'ordre des étapes est **imposé par le serveur** (`auth`) ; l'UI en est le reflet, y compris le
  blocage 5 min (`429`) et le miroir LED (contrat §5.3).
- Aucune image n'est conservée côté client ; la trame JPEG base64 part vers `auth`.

## État

- ✅ Login à étapes + capture webcam + miroir LED + gestion blocage/rejets — **14 tests Vitest**.
- 🟨 Écran **habilitations** (enrôlement des visages + rôles) — lot **L6** (placeholder actuel).

## Place dans le flux

Consommateur de `auth` (étapes) ; pour l'enrôlement (L6), de `auth → face-id`. Ne manipule aucun
secret et ne fait pas foi pour les habilitations (décision côté `auth`, claim `role` du JWT).
