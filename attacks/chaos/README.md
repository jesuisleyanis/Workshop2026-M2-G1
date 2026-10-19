# Chaos engineering — pannes non-attaque

> Complète le banc d'essai Red Team (`attacks/`). Ici on n'attaque pas : on injecte des
> **pannes qui ne sont pas des attaques** (crash de processus, gel momentané) pour prouver
> que la plateforme se rétablit grâce à sa **résilience intrinsèque** — restart policy
> `unless-stopped`, healthchecks — indépendamment de la chaîne attaque → détection ML →
> remédiation. C'est une exigence de recette (ROADMAP J4).

## Différence avec `attacks/`

| | `attacks/` (Red Team) | `attacks/chaos/` (chaos) |
|---|---|---|
| Déclencheur | attaque depuis le PC Attaquant | panne injectée côté opérateur (PC Hôte) |
| Détection | modèle ML (`incident_type`) | healthcheck / restart policy |
| Preuve | `verify_tx` OK après remédiation | `verify_tx` OK après auto-reprise |

## Pannes livrées

| Panne | Effet | Reprise attendue |
|---|---|---|
| `crash` | `docker kill` du conteneur (mort brutale du process) | la restart policy `unless-stopped` relance ; healthcheck repasse vert |
| `freeze` | `docker pause` N s (gel SIGSTOP) puis `unpause` automatique | dégel en fin de fenêtre, service de nouveau réactif |

## Garde-fous

- Cible **uniquement** les conteneurs du projet `resilience-g1`, liste blanche
  `payment-api auth front` (jamais la DB, les secrets, l'observabilité).
- Pannes **bornées** (durée plafonnée à 30 s) et **réversibles** : aucune suppression de
  conteneur/volume, aucune perte de données.
- **Kill-switch** : `chaos.sh --stop` dé-gèle tout conteneur resté en pause et nettoie.
- Journal horodaté dans `attacks/.runlog` (corrélation MTTR).

## Lancement (sur le PC Hôte, stack up)

```bash
make verify                                   # état "avant" OK
attacks/chaos/chaos.sh crash  --service payment-api
attacks/chaos/chaos.sh freeze --service payment-api --duration 15
attacks/chaos/chaos.sh --stop                 # kill-switch
make verify                                   # après : doit repasser OK seul
```

## Tests

```bash
python -m pytest attacks/tests/test_chaos.py -q          # contrat statique (garde-fous)
RESILIENCE_E2E=1 pytest tests/e2e/test_chaos_flow.py -q   # reprise réelle (stack up)
```
