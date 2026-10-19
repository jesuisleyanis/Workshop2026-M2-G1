# Tests end-to-end

Rejouent la chaîne complète **avant → attaque → détection → remédiation → après** contre une stack réelle.

```bash
make up            # lève la stack (profil demo)
make seed          # données fictives (SEED_PASSWORD depuis .env, cf. scripts/README.md)
RESILIENCE_E2E=1 pytest tests/e2e -q
```

Désactivés par défaut (sautés) pour ne pas dépendre de Docker dans la suite unitaire.

## Couverture (les 4 scénarios)

| Test | Scénario | Preuve de reprise autonome |
|---|---|---|
| `test_avant_service_utilisable` | — | `verify_tx` OK à l'état « avant » |
| `test_recovery_after_network_attack` | `service_flood`, `auth_abuse`, `web_attack` | service utilisable après l'attaque bornée (lancée via `attacks/run.sh`) |
| `test_recovery_after_data_corruption` | `data_corruption` | `verify_tx` **KO** après injection **puis OK seul** → la restauration a bien agi |

`data_corruption` s'injecte côté hôte via les playbooks `infra/ansible/playbooks/pg_backup.yml` puis `db_corrupt_fake.yml` (la base n'est pas exposée) ; le test annule l'altération en `finally` si la remédiation n'a pas restauré. Sauté si `ansible-playbook` est absent.

## Variables d'environnement

| Variable | Rôle | Défaut |
|---|---|---|
| `RESILIENCE_E2E=1` | active les tests e2e | désactivé |
| `BASE_URL` | point d'entrée (WAF) | `https://localhost` |
| `SEED_PASSWORD` (ou `VERIFY_PASSWORD`) | mot de passe du jeu fictif, requis par `verify_tx` (`set -a; . .env`) | — |
| `REMEDIATION_BASE` + `REMEDIATION_TOKEN` | *(optionnel)* interroge `GET /incidents` du moteur pour **prouver qu'un incident du bon type a été clos** (`status="closed"`). Sans ces variables, la preuve repose sur `verify_tx`. | non renseigné |

Chaque scénario de `attacks/scenarios/` est rejoué et doit se solder par un `verify_tx` OK **sans intervention humaine** — c'est la preuve attendue par le jury (Axe 1).
