# Gestion des secrets — SOPS + age

> Couvre l'exigence **R13** (gestion des secrets) et la contrainte §7.4 du sujet : **aucun secret en clair dans l'archive `Code.zip`**.

## Principe

- Les secrets sont stockés **chiffrés** dans le dépôt (`secrets.enc.env`), déchiffrables uniquement avec la **clé privée age** de l'équipe, qui n'est **jamais commitée**.
- Au lancement, `scripts/decrypt-secrets.sh` produit un `.env` local (ignoré par git) consommé par Docker Compose.
- Pour la correction/jury, une **clé de démo** est fournie **hors archive** (clé USB / canal privé), jamais dans le zip.

## Secrets gérés

| Variable | Usage | Composant |
|---|---|---|
| `JWT_SECRET` | signature des JWT | auth |
| `POSTGRES_PASSWORD` | mot de passe DB | postgres, payment-api, auth |
| `REMEDIATION_TOKEN` | auth de `POST /events` | detector → remediation |
| `INTERNAL_TOKEN` | auth de `/internal/*` | remediation → auth |

## Mise en place (une fois par poste)

```bash
# 1. Installer les outils
brew install sops age          # ou apt/choco selon l'OS

# 2. Générer la clé age de l'équipe (UNE fois, partagée hors git)
age-keygen -o ~/.config/sops/age/keys.txt
#   -> copier la clé PUBLIQUE (age1...) dans security/sops/.sops.yaml

# 3. Créer et chiffrer les secrets
cp security/sops/secrets.example.env security/sops/secrets.enc.env
#   éditer avec de vraies valeurs (openssl rand -hex 32 pour les tokens)
sops --encrypt --in-place security/sops/secrets.enc.env

# 4. Au lancement (fait par `make up`)
export SOPS_AGE_KEY_FILE=~/.config/sops/age/keys.txt
scripts/decrypt-secrets.sh
```

## Garde-fous

- `.gitignore` bloque `.env`, `*.age`, `keys.txt`.
- `gitleaks` en pre-commit (voir `security/hardening/`) empêche un secret en clair d'être commité.
- `security/hardening/audit.sh` vérifie l'absence de secret en clair avant packaging.
- **Jamais** committer `secrets.enc.env` en version déchiffrée, ni la clé privée.

## Vault (option)

HashiCorp Vault en mode dev reste une alternative acceptée par le sujet. SOPS est retenu par défaut pour sa simplicité sur 16 Go de RAM et son intégration git naturelle.
