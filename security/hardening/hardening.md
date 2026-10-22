# Durcissement — RESILIENCE-ALPHA

> Couvre **R14** (durcissement des composants et des accès) et **R15** (privilèges maîtrisés du moteur de remédiation). Le jury sonde explicitement ces points (sujet §3.4, Axe 2).

## Checklist appliquée à chaque conteneur

| Mesure | Détail | Vérifié par |
|---|---|---|
| Image slim | `python:3.12-slim`, `nginx:alpine`, multi-stage pour les fronts | revue Dockerfile |
| Utilisateur non-root | `USER app` (uid ≥ 1000), pas de process en root | revue Dockerfile |
| Capabilities | `cap_drop: ALL` ; ajout explicite uniquement si indispensable (aucun `cap_add` à ce jour, voir ci-dessous) | `audit.sh` (ancre présente), `infra/tests/test_compose_hardening.py` (par service) |
| `no-new-privileges` | `security_opt: ["no-new-privileges:true"]` | compose, `infra/tests/test_compose_hardening.py` |
| Système de fichiers | `read_only: true` + `tmpfs` pour les écritures nécessaires, **quand le service le permet** (exceptions documentées : `docker-socket-proxy`, `pg-exporter`, `cadvisor`) | compose |
| Limites ressources | `mem_limit` par service ; `cpus` sur les services Python (ancre `x-pylimits`) — 16 Go partagés | compose |
| Healthcheck | `/health` sur chaque service ; `HEALTHCHECK` dans le Dockerfile | Dockerfile |
| Réseau | services internes sur `app`/`data`/`obs` ; `data` en `internal: true` ; **seuls le WAF (80/443, 9443 en loopback) et mosquitto (1883 sur l'IP hotspot)** publient des ports | `audit.sh` |
| Contexte de build | `.dockerignore` racine : `.env`, clés age, `.git`, `.venv`, caches exclus du contexte des 8 images construites depuis la racine — un `COPY` trop large ne peut pas embarquer de secret déchiffré | `infra/tests/test_launch_contract.py` |
| Secrets | via SOPS uniquement, injectés en env au runtime ; aucun secret applicatif en image. **Exception de labo** : le certificat TLS auto-signé du WAF est généré au build et figé dans une couche (clé privée partagée entre instances) — acceptable pour une démo, à régénérer au démarrage en production | gitleaks + `audit.sh` |

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
- Accès Docker **médié par `docker-socket-proxy`** (HAProxy, `remediation/proxy/haproxy.cfg`, ADR 0002) : liste blanche stricte de 5 couples méthode/chemin (`GET _ping`, `GET containers/json`, `GET containers/{id}/json`, `POST containers/{id}/restart`, `POST containers/{id}/kill?signal=HUP`), tout le reste → 403. Le socket est monté en lecture seule **uniquement** dans le proxy. HAProxy tourne en utilisateur `haproxy` (non-root) avec le seul **groupe** propriétaire du socket (`group_add: ["0"]`, pas d'uid 0) : sans lui, chaque appel échouait en 503 et aucun `restart_service` ne pouvait réussir (corrigé le 21/10). Vérifié : `POST /containers/create` reste refusé (403).
- **Blocage d'IP sous Docker Desktop** : le WAF voit tous les clients externes avec l'IP d'une passerelle Docker. Les réseaux du WAF ont des sous-réseaux fixes, entièrement protégés par `NEVER_BLOCK_IPS` (plages CIDR) et exclus de la désignation d'IP source par le detector : un blocage ne peut ni couper tous les clients, ni viser un service interne (la remédiation s'était bloquée elle-même via son trafic `verify_tx`).
- API `/events` du moteur **authentifiée** (token `REMEDIATION_TOKEN`), service **non exposé** sur `edge`.
- **Écritures humaines** (déblocage d'IP depuis le dashboard) : jeton **opérateur** distinct `REMEDIATION_OPERATOR_TOKEN`, connu du seul moteur ; le jeton de service y est refusé (403). Le nginx du dashboard injecte le jeton de service sur ses routes de **lecture** (GET seul) mais **aucun jeton** sur les écritures : il relaie celui que l'opérateur saisit. Un conteneur du réseau `app` ou un processus local (dashboard sur `127.0.0.1:8081`) ne peut donc rien écrire sans ce secret (`infra/tests/test_dashboard_proxy.py`).
- Rappel proxy Docker : `group_add: ["0"]` donne à HAProxy (non-root) le **seul groupe** propriétaire du socket (pas l'uid 0) ; la restriction effective reste la liste blanche des 5 couples (cf. ci-dessus). C'est un écart assumé au moindre privilège : sans lui aucun `restart_service` ne fonctionne.
- Garde-fous applicatifs : `cooldown`, `max_attempts`, `dry_run` (voir `remediation/decision_table.yml`).
- **Racine en lecture seule** (`read_only: true`, comme payment-api/auth) : les seuls points inscriptibles sont `/tmp` (tmpfs, artefacts ansible-runner) et le **volume nommé `remediation-journal`** monté sur `/var/lib/remediation`. Le journal d'incidents SQLite **survit donc au redémarrage** du conteneur, conformément à la CDC §5.4 (ticket #22).

## Assistant RAG (profil `ai`)

- `ollama` porte désormais l'ancre de durcissement commune (`no-new-privileges:true` + `cap_drop: ALL`) : le serveur tourne en user space et n'a besoin d'aucune capability (ticket #22). Image épinglée (plus de `:latest`, R5).

## Outils

```bash
# Scan de secrets (pre-commit)
gitleaks detect --source . --no-banner

# Scan de vulnérabilités d'images (avant jury) — nom réel produit par compose (préfixe projet)
trivy image resilience-g1-payment-api        # ou : trivy config infra/compose/docker-compose.yml

# Audit de configuration du repo (local, rapide)
security/hardening/audit.sh
```

`gitleaks` et `trivy` sont documentés ici et branchés en pre-commit / avant packaging ; ils ne sont pas exécutés en CI pour l'instant (décision équipe).

### Contrôles de `audit.sh` (exit 0 = conforme, réutilisable en CI)

1. Socket Docker jamais touché par le moteur ; aucun montage en lecture-écriture.
2. Aucun conteneur `privileged: true`.
3. Aucun secret en clair (hors exemples factices).
4. Aucune clé age (`keys.txt`, `*.age`) dans le dépôt.
5. **Exposition réseau** : seuls le WAF et mosquitto (bind hotspot, jamais `0.0.0.0`) publient des ports (R11/R19) — tout autre service `ports:` fait échouer l'audit.
6. **Durcissement** : ancre `no-new-privileges:true` + `cap_drop: ALL` présente dans le compose.
7. **DB interne** : réseau `data` en `internal: true` (Postgres jamais joignable depuis l'hôte).
