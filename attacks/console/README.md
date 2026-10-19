# Console Red Team

Interface de pilotage **locale** du banc d'essai (`attacks/`) : lancer les scénarios,
suivre la chaîne de reprise et le journal temps réel, kill-switch et reset — en un écran.

> ⚠️ **Local-only.** À lancer **uniquement sur le PC Attaquant**, bindé sur `127.0.0.1`.
> Ce service déclenche des générateurs d'attaque : **ne jamais l'exposer** sur le réseau.

## Ce qu'elle fait (et ne fait pas)

- Enveloppe `attacks/run.sh`, `reset.sh` et `scripts/verify_tx` derrière une petite API.
- Les **garde-fous sont côté serveur** et non contournables depuis l'UI : plafonds
  `rate ≤ 100/s` et `duration ≤ 60 s` (clampés), liste blanche de scénarios, cible validée.
- Lance uniquement les scénarios **réseau** (`service_flood`, `auth_abuse`, `web_attack`).
  `data_corruption` reste **opérateur-only** (base non exposée) — rappelé dans l'UI.
- La détection ML et la remédiation s'observent sur le **dashboard Blue Team**. Par défaut
  la console l'indique honnêtement (nœuds « Détection/Remédiation » en attente, preuve =
  `verify_tx`). Avec la **liaison Bleu** (ci-dessous), ces nœuds affichent les **MTTD/MTTR
  réels** lus sur le moteur de remédiation.

## Liaison Bleu (optionnelle) — détection & remédiation réelles

Le PC Attaquant **ne peut pas** joindre le moteur (réseau interne, R19) : la liaison ne
fonctionne que là où le moteur est accessible — **sur le PC Hôte**, ou si la console tourne
en conteneur sur le réseau `app`. Le backend relaie `GET /incidents` en lecture seule ; le
**token reste côté serveur** (jamais envoyé au navigateur).

```bash
REMEDIATION_BASE=http://localhost:8005 \   # ou http://remediation:8005 en conteneur
REMEDIATION_TOKEN=<token SOPS> \
  python -m uvicorn --app-dir attacks/console server:app --host 127.0.0.1 --port 8088
```

Absente ou injoignable, la liaison se désactive proprement (relais `/api/blue/incidents`
en 503/502) et la console retombe sur la preuve `verify_tx`.

## Lancer

```bash
pip install -r attacks/console/requirements.txt
RESILIENCE_TARGET=https://192.168.137.1 \
  python -m uvicorn --app-dir attacks/console server:app --host 127.0.0.1 --port 8088
# puis ouvrir http://127.0.0.1:8088
```

Variables : `RESILIENCE_TARGET` (cible par défaut), `CONSOLE_PORT` (défaut 8088),
`RESILIENCE_CONSOLE_DRY=1` (mode démo sans lancer d'attaque réelle — utilisé par les tests).

## API

| Méthode | Route | Rôle |
|---|---|---|
| GET | `/api/scenarios` | scénarios + contrat (signal, incident_type, remédiation) + plafonds |
| POST | `/api/run` | lance un scénario (params clampés côté serveur) |
| POST | `/api/stop` | kill-switch (`run.sh --stop`) |
| POST | `/api/reset` | `reset.sh` (état « avant ») |
| GET | `/api/status` | scénario en cours, chrono, reste |
| GET | `/api/verify` | `verify_tx` (preuve avant/après) |
| GET | `/api/stream` | SSE : journal `.runlog` + statut |
| GET | `/api/blue/incidents` | relais lecture seule du moteur (si liaison Bleu configurée) |

## Tests

```bash
python -m pytest attacks/tests/test_console.py -q   # garde-fous (dry-run, sans attaque réelle)
```
