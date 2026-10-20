# backoffice — back-office durci (consigne additionnelle 1)

> **Statut : à construire** (lot L3 du [backlog](../../docs/consigne-additionnelle-1-roadmap.md)).
> Le [cahier des charges](CAHIER-DES-CHARGES.md) fige le périmètre ; le backend consommé est déjà
> spécifié ([`docs/contracts.md §5`](../../docs/contracts.md#5-consigne-additionnelle-1--authentification-renforcée-du-back-office)) et testé (`services/auth`, `services/face-id`).

Application React + Vite + TypeScript + Tailwind (stack identique à `services/front`), réservée
aux rôles `operator`/`admin`, servie derrière le WAF.

## À l'amorçage (L3-1)

```bash
npm create vite@latest . -- --template react-ts
# puis Tailwind + le client API (réutiliser services/front/src/api) + Vitest + Testing Library
```

## Flux de connexion (contrat §5.2)

```
identifiant ──POST /auth/identify──► caméra ON (getUserMedia, caméra du PC Hôte)
   trame ────POST /auth/face───────► reconnu ? ─oui─► champ mot de passe
                                               └non─► identifiant vidé, caméra OFF, LED rouge
   mot de passe ─POST /auth/password► OK (rôle privilégié) ─► back-office
```

Caméra : `getUserMedia` dans le **navigateur de l'hôte** (ADR 0005), active seulement pendant
l'identification, arrêtée ensuite. Tests : `getUserMedia` **mocké** (aucun matériel requis).

## Place dans le flux

`backoffice` est un **consommateur** de `auth` (étapes) et, pour l'enrôlement, de `auth → face-id`.
Il ne manipule aucun secret et ne fait pas foi pour les habilitations (décision côté `auth`).
