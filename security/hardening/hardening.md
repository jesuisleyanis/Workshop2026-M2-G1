# Durcissement — RESILIENCE-ALPHA

> Couvre **R14** (durcissement des composants et des accès) et **R15** (privilèges maîtrisés du moteur de remédiation). Le jury sonde explicitement ces points (sujet §3.4, Axe 2).

## Checklist appliquée à chaque conteneur

| Mesure | Détail | Vérifié par |
|---|---|---|
| Image slim | `python:3.12-slim`, `nginx:alpine`, multi-stage pour les fronts | revue Dockerfile |
| Utilisateur non-root | `USER app` (uid ≥ 1000), pas de process en root | `audit.sh` |
| Capabilities | `cap_drop: ALL` ; ajout explicite uniquement si indispensable (aucun `cap_add` à ce jour, voir ci-dessous) | `audit.sh` compose, `infra/tests/test_compose_hardening.py` |
| `no-new-privileges` | `security_opt: ["no-new-privileges:true"]` | compose |
| Système de fichiers | `read_only: true` + `tmpfs` pour les écritures nécessaires | compose |
| Limites ressources | `cpus`, `mem_limit` par service (16 Go partagés) | compose |
| Healthcheck | `/health` sur chaque service ; `HEALTHCHECK` dans le Dockerfile | Dockerfile |
| Réseau | services internes sur `app`/`data`/`obs` ; `data` en `internal: true` ; **seul le WAF** publie des ports | `audit.sh` |
| Secrets | via SOPS uniquement, injectés en env au runtime ; aucun secret en image | gitleaks + `audit.sh` |

## Cas particulier : Postgres sous `cap_drop: ALL` (ticket #11)

L'image `postgres:16-alpine` démarre en root puis redescend vers `postgres` : son entrypoint fait
`chown` du répertoire de données et `gosu` — ce qui exige `CHOWN`, `SETUID`, `SETGID` (et souvent
`DAC_OVERRIDE`, `FOWNER`). Toutes capabilities retirées, l'init d'un volume neuf échoue.

Choix retenu : **démarrer directement non-root** (`user: "70:70"`, l'uid/gid `postgres` de
l'image alpine) plutôt qu'ajouter des capabilities. L'entrypoint saute alors les étapes
privilégiées ; le volume nommé `pgdata` hérite de l'appartenance `70:70` du répertoire de l'image
à sa création ; `/var/run/postgresql` est déjà inscriptible par ce groupe dans l'image. Résultat :
`cap_drop: ALL` **sans aucun `cap_add`** — c'est le moindre privilège, et c'est plus fort que la
variante « root + cap_add minimal ».

Conséquences à connaître : un volume `pgdata` créé **avant** ce changement (appartenant à root)
doit être recréé (`docker compose down -v` puis `make up`) ; les playbooks (`db_corrupt_fake.yml`,
`pg_backup.yml`) passent par `docker exec … psql -U resilience`, qui s'exécute donc en uid 70 — rien
à adapter. Validation live (volume vierge → `healthy`) à rejouer sur une machine avec Docker.

## Moteur de remédiation — modèle de privilèges (critique)

- **Jamais** de montage direct de `/var/run/docker.sock` dans le conteneur de remédiation : ce serait un accès root-équivalent sur l'hôte.
- Accès Docker **médié par `docker-socket-proxy`** (HAProxy, `remediation/proxy/haproxy.cfg`, ADR 0002) : liste blanche stricte de 5 couples méthode/chemin (`GET _ping`, `GET containers/json`, `GET containers/{id}/json`, `POST containers/{id}/restart`, `POST containers/{id}/kill?signal=HUP`), tout le reste → 403. Le socket est monté en lecture seule **uniquement** dans le proxy.
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

### Contrôles de `audit.sh` (exit 0 = conforme, réutilisable en CI)

1. Socket Docker jamais touché par le moteur ; aucun montage en lecture-écriture.
2. Aucun conteneur `privileged: true`.
3. Aucun secret en clair (hors exemples factices).
4. Aucune clé age (`keys.txt`, `*.age`) dans le dépôt.
5. **Exposition réseau** : seul le WAF publie des ports (R11/R19) — tout autre service `ports:` fait échouer l'audit.
6. **Durcissement** : ancre `no-new-privileges:true` + `cap_drop: ALL` présente dans le compose.
7. **DB interne** : réseau `data` en `internal: true` (Postgres jamais joignable depuis l'hôte).
