# Cahier des charges — Gestion des secrets (security/sops/)

## Rôle et exigences couvertes

Gestion des secrets de toute la plateforme par chiffrement au repos. Couvre :
- **R13** — gestion des secrets (SOPS + age, alternative Vault acceptée par le sujet).
- Contrainte **§7.4** du sujet — aucun secret en clair dans l'archive `Code.zip`.

## Périmètre

- Chiffrement/déchiffrement des secrets avec SOPS + age.
- `secrets.enc.env` **chiffré** commité ; `secrets.example.env` (valeurs factices) comme modèle.
- Déchiffrement au lancement vers un `.env` local **non commité** (`scripts/decrypt-secrets.sh`).
- Règles `.sops.yaml` et `.gitignore` empêchant toute fuite (clés age, `.env`).

Hors périmètre : rotation automatique en production, HSM, Vault en haute disponibilité (profil optionnel seulement).

## Secrets gérés

| Variable | Usage | Composant |
|---|---|---|
| `JWT_SECRET` | signature des JWT | auth, payment-api |
| `POSTGRES_PASSWORD` | mot de passe DB | postgres, services |
| `REMEDIATION_TOKEN` | auth de `POST /events` | detector → remediation |
| `INTERNAL_TOKEN` | auth de `/internal/*` | remediation → auth |
| `SEED_PASSWORD` | mot de passe des comptes fictifs du seed | `make seed`, `scripts/verify_tx`, remediation (verify) |

## Contraintes de sécurité

- La **clé privée age** n'est **jamais** commitée (hors git, partagée hors bande).
- Pour le jury : une **clé de démo** est fournie **hors archive**, jamais dans le zip.
- `gitleaks` en pre-commit + `security/hardening/audit.sh` vérifient l'absence de secret en clair.

## Critères d'acceptation

- [ ] `secrets.enc.env` est illisible sans la clé age.
- [ ] `scripts/decrypt-secrets.sh` produit un `.env` fonctionnel avec la clé.
- [ ] `git status` ne montre jamais `.env`, `keys.txt`, `*.age`.
- [ ] `package_deliverables.sh` refuse de livrer si un secret en clair est détecté.

## Vérification

```bash
security/hardening/audit.sh     # inclut le contrôle "secrets en clair" et "clés age"
```
