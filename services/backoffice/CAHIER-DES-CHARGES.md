# Cahier des charges — `services/backoffice`

> Composant de la **Consigne Additionnelle 1** (cadrage : [`docs/consigne-additionnelle-1.md`](../../docs/consigne-additionnelle-1.md), lot **L3** ; décision [ADR 0004](../../docs/adr/0004-backoffice-app-dediee.md)).
> **Statut : à construire.** Ce CDC fige le périmètre ; le backend (auth à étapes, face-id, LED) est déjà spécifié et indépendant de cette UI.

## 1. Rôle

**Back-office privilégié** du SI : la surface d'**administration** réservée aux rôles `operator`/`admin`. Il porte (1) le **login à étapes durci** (identifiant → visage → mot de passe) et (2) la **gestion complète des habilitations** (rôles + enrôlement/révocation des visages). Application React + Vite + TypeScript + Tailwind (même stack que `services/front`), servie **derrière le WAF** sur une route/vhost dédiée.

- Port interne **8080** (nginx), réseau **`edge`** (via WAF) + appels API vers `auth`. Jamais exposé directement.

## 2. Exigences couvertes

| Réf. | Exigence | Comment |
|---|---|---|
| **CA1** | Saisie identifiant puis caméra USB (PC Hôte) | `getUserMedia()` dans le navigateur de l'hôte ([ADR 0005](../../docs/adr/0005-camera-navigateur-hote.md)) |
| **CA3** | Visage reconnu ⇒ mot de passe ; sinon identifiant vidé + caméra OFF | machine à états UI alignée sur `auth` (contrat §5.2) |
| **CA5** | Gestion complète des habilitations | écran rôles + enrôlement/révocation (via `auth` → `face-id`) |
| **CA7** | Témoin visuel aligné sur la LED | indicateur d'état miroir des 5 états |
| **R11/R14** | Derrière WAF, durci | nginx non-root, `read_only` + tmpfs (parité `front`) |

## 3. Écrans

1. **Connexion à étapes.** (a) identifiant → `POST /auth/identify` → active la caméra ; (b) capture d'une trame → `POST /auth/face` → reconnu : champ mot de passe ; non reconnu : identifiant vidé, caméra éteinte, message + décompte ; (c) mot de passe → `POST /auth/password` → ouverture back-office. Gère le **blocage 5 min** (`429`) et le **miroir LED**.
2. **Habilitations** (rôle `admin`). Liste des utilisateurs + rôles ; enrôlement d'un visage par webcam (multi-prises) ; révocation ; état d'enrôlement (sans aucune donnée biométrique affichée).

## 4. Sécurité

- Caméra active **uniquement** pendant l'étape d'identification, coupée ensuite (`MediaStreamTrack.stop()`).
- La trame est transmise à `auth` via HTTPS (WAF) ; jamais stockée côté client.
- L'accès au back-office exige un **rôle privilégié** (vérifié côté `auth`, claim JWT) : l'UI ne fait pas foi.
- Aucun secret dans le bundle (servi derrière le WAF, visible du PC Attaquant) — cf. `front`.

## 5. Critères d'acceptation (tests Vitest — `getUserMedia` mocké)

| # | Critère |
|---|---|
| B1 | L'ordre des étapes est imposé : pas de champ mot de passe avant « reconnu ». |
| B2 | Visage rejeté ⇒ identifiant vidé + caméra arrêtée + message. |
| B3 | Blocage (`429`) ⇒ écran de blocage avec décompte. |
| B4 | Enrôlement : capture multi-prises → appel d'enrôlement ; gating rôle `admin`. |
| B5 | Le témoin d'état reflète les 5 états (idle/recognized/auth_ok/auth_fail/not_recognized). |

## 6. Hors périmètre

- Pas de refonte des écrans métier (ils restent dans `front`).
- Option B (greffer sur `front`) : si retenue, ce périmètre devient un module de `front` ; le backend est inchangé.
