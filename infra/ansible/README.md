# infra/ansible — déploiement et plan d'exécution de la remédiation

> Couvre **R6** (opérations par playbooks Ansible) et sert **R3/R15** (moteur de remédiation à privilèges maîtrisés).

## Deux familles de playbooks, deux lieux d'exécution

| Dossier | Exécuté par | Où | Accès |
|---|---|---|---|
| `playbooks/*.yml` (**opérateur**) : `deploy.yml`, `pg_backup.yml`, `db_corrupt_fake.yml` | un humain / `attacks/run.sh` / `tests/e2e` | **PC Hôte**, inventaire `inventory/hosts.ini` (connexion locale) | `docker compose`, `docker exec` sur Postgres (base non exposée) |
| `playbooks/remediation/*.yml` (**automate**) : `waf_deny_ip.yml`, `pg_restore.yml` | le moteur de remédiation (ansible-runner) | **dans le conteneur `remediation`**, `hosts: localhost` / `connection: local` | aucun `docker exec`, aucun socket Docker ; volume `waf-deny`, réseau `data`, dumps en lecture seule |

Le choix « tout dans le conteneur » (ticket #8) évite de donner au moteur un accès à l'hôte ou au
socket Docker (ADR 0002) : il n'obtient que ce dont chaque action a besoin.

```
PC Hôte                                     conteneur remediation (uid 10001, réseaux app+data)
───────                                     ──────────────────────────────────────────────────
pg_backup.yml ──► infra/ansible/backups/ ──ro──► /opt/backups ──► pg_restore.yml ──► postgres:5432 (data)
                                                                  waf_deny_ip.yml ──► volume waf-deny ──► waf (/etc/nginx/deny)
                                                                  moteur ──► docker-socket-proxy ──► POST /containers/{waf}/kill?signal=HUP
```

## Playbooks de remédiation (`playbooks/remediation/`)

| Playbook | Extravars (du moteur) | Effet | Idempotence |
|---|---|---|---|
| `waf_deny_ip.yml` | `deny_ip`, `deny_list` (`temporary`\|`permanent`), `incident_id` | `lineinfile` `"<ip> 1;"` dans `WAF_DENY_FILE` (défaut `/etc/resilience/waf-deny/blocked_ips.conf`). Le reload Nginx est fait **par le moteur** (SIGHUP via le proxy) uniquement si `changed`. | `changed=false` si l'IP est déjà présente ; IP non conforme → `assert` → échec |
| `pg_restore.yml` | `backup` (`latest` ou nom de fichier), `incident_id` | purge des tables en quarantaine (`*__corrupted`, artefacts du scénario), `pg_restore --clean --if-exists --no-owner --no-privileges` du dump le plus récent de `PG_BACKUP_DIR`, puis contrôle `SELECT count(*)` sur `users/accounts/transactions` | restaurer deux fois le même dump donne le même état ; échec explicite si aucun dump |

Variables d'environnement lues (`lookup('env')`) : `WAF_DENY_FILE`, `PG_BACKUP_DIR`, `POSTGRES_HOST/PORT/DB/USER/PASSWORD`.
Les playbooks sont copiés au build de l'image dans `/opt/ansible/project` (lecture seule) ; ansible-runner
écrit ses artefacts dans `/tmp/ansible-runner` (tmpfs). `ansible_python_interpreter` = le Python du moteur.

## Playbooks opérateur (`playbooks/`)

```bash
cd infra/ansible
ansible-playbook -i inventory/hosts.ini playbooks/deploy.yml            # secrets SOPS -> .env, compose up, attente WAF sain
ansible-playbook -i inventory/hosts.ini playbooks/pg_backup.yml         # dump sain -> backups/ (0644, lisible par le conteneur)
ansible-playbook -i inventory/hosts.ini playbooks/db_corrupt_fake.yml   # déclencheur data_corruption (réversible : -e mode=revert)
```

`inventory/hosts.ini` déduit `project_root` de son propre emplacement (`inventory_dir`) : **aucun chemin
machine en dur**, surcharge possible avec `-e project_root=...`.

`backups/` est ignoré par git (sauf `.gitkeep`) et monté **en lecture seule** dans le conteneur remediation.
Sans dump sain, `restore_pg_dump` échoue explicitement (« Aucun dump ») : jouer `pg_backup.yml` à l'état nominal
(c'est ce que font `attacks/run.sh data_corruption` et `tests/e2e`).

## Tests

```bash
python -m pytest -q remediation/tests/test_playbooks.py
```

Contrat moteur ↔ playbooks (extravars déclarées, `hosts: localhost`, jamais `docker exec`), `ansible-playbook
--syntax-check` de tous les playbooks avec l'inventaire réel, et exécution **réelle** de `waf_deny_ip.yml`
par ansible-runner sur un fichier temporaire (écriture, idempotence, IP invalide refusée).
La restauration Postgres complète est validée stack levée (`RESILIENCE_E2E=1 pytest tests/e2e`, scénario `data_corruption`).
