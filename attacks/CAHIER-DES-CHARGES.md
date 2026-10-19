# Cahier des charges — Banc d'essai de résilience (attacks/)

## Rôle et exigences couvertes

Éprouve la plateforme **sans sortir du laboratoire** (sujet §3.4) et fournit le déclencheur de la chaîne de reprise autonome. Couvre **R10** : au moins un scénario d'attaque exécuté depuis un **PC distinct**, produisant un **effet observable** par la supervision.

## Périmètre

| Dans le périmètre | Hors périmètre (interdit) |
|---|---|
| WAF du PC Hôte (`192.168.137.1`) sur le hotspot `RESILIENCE-G1` | Réseaux du campus, autres groupes |
| API/front du projet (données fictives) | Équipements tiers, services Internet |
| Génération de signal bornée | Destruction, exfiltration réelle, intensité non plafonnée |

## Contrat Red Team ↔ Blue Team (le cœur)

Chaque scénario `scenarios/<nom>.yml` **doit** déclarer, et c'est vérifié par `validate_scenarios.py` + tests :

- `name`, `objectif`, `cible` (service/endpoint), `prerequis` ;
- `signal_attendu` : la métrique Prometheus ou le motif Loki qui doit apparaître → relie au vecteur de features ML (`docs/contracts.md §2`) ;
- `incident_type` : valeur de l'énumération figée (`docs/contracts.md §3`) ;
- `remediation_attendue` : l'/les action(s) de `remediation/decision_table.yml` qui doivent se déclencher (`§4`) ;
- `critere_de_reussite` : **`verify_tx` repasse OK après remédiation, sans intervention humaine**.

C'est ce contrat qui garantit qu'une attaque est toujours reliée à une détection et à une action — pas un bruit gratuit.

## Scénarios livrés

| Scénario | incident_type | Signal | Remédiation attendue |
|---|---|---|---|
| `service_flood` | service_flood | req/s + 5xx + latence ↑ | waf_block_ip + restart_service |
| `auth_abuse` | auth_abuse | échecs 401 ↑ | waf_block_ip + tighten_rate_limit |
| `web_attack` | web_attack | blocages CRS ↑ | confirm_waf_block + waf_blacklist_ip |
| `data_corruption` | data_corruption | erreurs DB + verify_tx KO | restore_pg_dump (correction ≠ disponibilité) |

## Garde-fous (critères d'acceptation)

- Intensité et durée **plafonnées** (`run.sh` borne `rate ≤ 100/s`, `duration ≤ 60 s`).
- **Arrêt automatique** en fin de fenêtre + **kill-switch** (`run.sh --stop`).
- **Idempotence / réversibilité** : `reset.sh` ramène à l'état « avant ».
- **Journalisation** horodatée début/fin (`.runlog`) pour corréler avec MTTD/MTTR.
- Données **100 % fictives**.

## Lancement

Voir `attacks/README.md`. En démo notée : depuis le **PC Attaquant physique**. En dev : profil Compose `attack`.

## Tests

```bash
python -m pytest attacks/tests/ -q   # valide le contrat de tous les scénarios
```
