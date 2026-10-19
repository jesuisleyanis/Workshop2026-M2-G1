# Banc d'essai de résilience (Red Team) — RESILIENCE-ALPHA

> Couvre **R10**. Ces scénarios éprouvent la chaîne détection → remédiation → vérification sur **le seul SI du projet**. Ils génèrent un **signal observable** (pic de trafic, échecs d'auth, blocages WAF, erreurs DB), bornés en intensité et en durée, pour déclencher la reprise autonome — **pas** pour maximiser des dégâts.

## Règles de périmètre (strictes)

- Cible **exclusive** : la stack du projet (WAF du PC Hôte, `192.168.137.1`, réseau hotspot `RESILIENCE-G1`).
- **Interdit** : réseaux du campus, autres groupes, équipements tiers, services accessibles sur Internet.
- Données **fictives** uniquement (comptes/transactions seedés).
- Chaque scénario : **durée bornée**, **intensité plafonnée**, **arrêt automatique**.
- Toute sortie du périmètre autorisé = arrêt immédiat + signalement au coach.

## Topologie

```
PC Attaquant (autre PC du groupe)            PC Hôte (192.168.137.1)
  outils de test ──HTTPS──────────────────►  WAF (443)  ──►  front / API
```

- **Démo notée & Clip Chrono** : l'attaque part du **PC Attaquant physique** (exigé par le sujet, Axe 1).
- **Dev / répétition** : le profil Compose `attack` rejoue le même scénario depuis un conteneur sur le PC Hôte (cible le WAF via l'hôte). Fallback uniquement.

> **Procédure complète pas-à-pas depuis le PC Attaquant : [`RUNBOOK-PC-ATTAQUANT.md`](RUNBOOK-PC-ATTAQUANT.md)** (pré-vol, lancement, observation, MTTD/MTTR, kill-switch, ordre pour le Clip Chrono).

## Mise en place

```bash
# 1. Vérifier la connectivité vers la cible (depuis le PC Attaquant)
curl -k https://192.168.137.1/api/v1/accounts -o /dev/null -w '%{http_code}\n'

# 2. Vérifier l'état "avant" (doit être OK)
make verify            # scripts/verify_tx -> exit 0

# 3. Lancer un scénario (intensité/durée plafonnées par défaut)
attacks/run.sh service_flood --target https://192.168.137.1 --duration 20 --rate 50

# 4. Observer : anomaly_score monte (Grafana/dashboard), la remédiation agit,
#    verify_tx repasse OK automatiquement, MTTR affiché.
```

## KILL-SWITCH

```bash
attacks/run.sh --stop        # arrête tout scénario en cours (SIGTERM aux générateurs)
attacks/reset.sh             # remet la cible à l'état "avant" (re-seed + redéploiement)
```

Chaque exécution journalise début/fin horodatés dans `attacks/.runlog` pour corréler avec le MTTD/MTTR mesuré côté Blue Team.

## Contrat Red Team ↔ Blue Team

Chaque scénario (`scenarios/*.yml`) **déclare** son `signal_attendu` (métrique Prometheus / motif Loki) et sa `remediation_attendue` (action de `remediation/decision_table.yml`). C'est le contrat qui relie l'offensive à la défense : voir `CAHIER-DES-CHARGES.md`.
