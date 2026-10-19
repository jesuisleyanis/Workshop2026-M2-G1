# Durcissement — RESILIENCE-ALPHA

> Couvre **R14** (durcissement des composants et des accès) et **R15** (privilèges maîtrisés du moteur de remédiation). Le jury sonde explicitement ces points (sujet §3.4, Axe 2).

## Checklist appliquée à chaque conteneur

| Mesure | Détail | Vérifié par |
|---|---|---|
| Image slim | `python:3.12-slim`, `nginx:alpine`, multi-stage pour les fronts | revue Dockerfile |
| Utilisateur non-root | `USER app` (uid ≥ 1000), pas de process en root | `audit.sh` |
| Capabilities | `cap_drop: ALL` ; ajout explicite uniquement si indispensable | `audit.sh` compose |
| `no-new-privileges` | `security_opt: ["no-new-privileges:true"]` | compose |
| Système de fichiers | `read_only: true` + `tmpfs` pour les écritures nécessaires | compose |
| Limites ressources | `cpus`, `mem_limit` par service (16 Go partagés) | compose |
| Healthcheck | `/health` sur chaque service ; `HEALTHCHECK` dans le Dockerfile | Dockerfile |
| Réseau | services internes sur `app`/`data`/`obs` ; `data` en `internal: true` ; **seul le WAF** publie des ports | `audit.sh` |
| Secrets | via SOPS uniquement, injectés en env au runtime ; aucun secret en image | gitleaks + `audit.sh` |

## Moteur de remédiation — modèle de privilèges (critique)

- **Jamais** de montage direct de `/var/run/docker.sock` dans le conteneur de remédiation : ce serait un accès root-équivalent sur l'hôte.
- Accès Docker **médié par `docker-socket-proxy`** (Tecnativa) configuré pour n'autoriser que les verbes nécessaires : `CONTAINERS=1`, `POST=1` restreint au `restart`, tout le reste à `0`.
- API `/events` du moteur **authentifiée** (token `REMEDIATION_TOKEN`), service **non exposé** sur `edge`.
- Garde-fous applicatifs : `cooldown`, `max_attempts`, `dry_run` (voir `remediation/decision_table.yml`).

## Outils

```bash
# Scan de secrets (pre-commit)
gitleaks detect --source . --no-banner

# Scan de vulnérabilités d'images (avant jury)
trivy image resilience/payment-api:latest

# Audit de configuration du repo (local, rapide)
security/hardening/audit.sh
```

`gitleaks` et `trivy` sont documentés ici et branchés en pre-commit / avant packaging ; ils ne sont pas exécutés en CI pour l'instant (décision équipe).
