# Runbook — exécution des scénarios depuis le PC Attaquant

> Procédure pas-à-pas pour jouer la chaîne **attaque → détection → remédiation → vérification** depuis le **PC Attaquant physique** (exigé par le sujet, Axe 1 / R10). Données 100 % fictives, périmètre strictement limité au SI du projet.
>
> Contexte et contrat : [`README.md`](README.md) · [`CAHIER-DES-CHARGES.md`](CAHIER-DES-CHARGES.md). Cadrage du pilier : [`../docs/cadrage-cyber.md`](../docs/cadrage-cyber.md).

## 0. Checklist de périmètre (à lire AVANT de lancer quoi que ce soit)

- [ ] Cible **exclusive** : le WAF du PC Hôte `192.168.137.1` sur le hotspot `RESILIENCE-G1`.
- [ ] **Interdit** : réseaux du campus, autres groupes, équipements tiers, tout service sur Internet.
- [ ] Le PC Attaquant est bien connecté au hotspot `RESILIENCE-G1` (et à **rien d'autre**).
- [ ] Toute sortie du périmètre autorisé → `run.sh --stop` immédiat + signalement au coach.

## 1. Prérequis sur le PC Attaquant

- `bash`, `curl`, `git` installés (Linux, WSL, ou Git Bash sous Windows).
- Le dépôt cloné (pour `attacks/run.sh`, `reset.sh`).
- Aucun accès privilégié à la stack n'est nécessaire : on ne parle qu'au WAF, en HTTPS.

## 2. Pré-vol : vérifier la connectivité et l'état « avant »

```bash
# a) Le WAF répond (403/401/200 attendus selon l'endpoint ; un code = joignable)
curl -k -s -o /dev/null -w 'WAF HTTP %{http_code}\n' https://192.168.137.1/api/v1/accounts

# b) État "avant" nominal : la transaction de contrôle passe (exit 0)
#    -> à lancer côté PC Hôte / opérateur, pas depuis l'attaquant :
make verify
```

Si (a) ne répond pas : vérifier le hotspot et l'IP ; ne pas forcer. Si (b) n'est pas OK : la stack n'est pas prête, prévenir l'équipe avant d'attaquer.

## 3. Jouer un scénario

Bornes de sécurité **imposées par `run.sh`** : `rate ≤ 100/s`, `duration ≤ 60 s`, arrêt automatique en fin de fenêtre.

```bash
# Le plus visible en démo — à jouer en premier :
attacks/run.sh service_flood --target https://192.168.137.1 --duration 20 --rate 50

# Les autres :
attacks/run.sh auth_abuse  --target https://192.168.137.1 --duration 30 --rate 40
attacks/run.sh web_attack  --target https://192.168.137.1 --duration 20 --rate 20
```

> `data_corruption` ne se lance **pas** depuis le PC Attaquant (la base est sur le réseau interne `data`, non exposée). C'est une altération réversible de données fictives déclenchée **côté opérateur / PC Hôte** via playbook Ansible — voir `scenarios/data_corruption.yml`. Procédure séparée (hors ce runbook attaquant).

## 4. Observer la reprise autonome (côté Blue Team / dashboard)

Pour chaque scénario, vérifier dans l'ordre que :

1. **Signal** — le `signal_attendu` du scénario apparaît (métrique Prometheus / motif Loki, cf. l'en-tête de `scenarios/<nom>.yml`).
2. **Détection** — `anomaly_score` monte, un `AnomalyEvent` du bon `incident_type` est émis (ML).
3. **Remédiation** — les actions de `remediation/decision_table.yml` pour cet `incident_type` se déclenchent (ex. `service_flood` → `waf_block_ip` + `restart_service`).
4. **Après** — `verify_tx` repasse **OK sans intervention humaine** ; le dashboard affiche le retour nominal.

### Mesure MTTD / MTTR
- **MTTD** = instant du `START <scenario>` dans `attacks/.runlog` → instant de l'`AnomalyEvent`.
- **MTTR** = instant de l'`AnomalyEvent` → instant où `verify_tx` repasse OK.
- Corréler avec les horodatages `START`/`END` de `attacks/.runlog` (chaque run y est journalisé).

## 5. Kill-switch et retour à l'état « avant »

```bash
attacks/run.sh --stop     # arrête tout scénario en cours (SIGTERM aux générateurs)
attacks/reset.sh          # vide la blocklist WAF, re-seed les données fictives, redéploie
```

`reset.sh` est **idempotent** : relançable sans effet de bord. À exécuter entre deux prises pour repartir d'un état propre (utile pour le Clip Chrono).

## 6. Vérification du banc d'essai (avant le jour J)

Les scénarios et leur contrat Red/Blue sont validés hors-ligne :

```bash
python attacks/validate_scenarios.py   # chaque scénario déclare bien le contrat
python -m pytest attacks/tests/test_scenarios.py -q   # 4 tests contrat (scénarios)
```

## 7. Ordre conseillé pour la démo notée / le Clip Chrono

1. `make verify` → **avant** OK (filmer l'écran nominal).
2. `attacks/run.sh service_flood ...` depuis le PC Attaquant → **attaque**.
3. Laisser la chaîne détecter et remédier → **détection + remédiation** (dashboard).
4. `verify_tx` OK automatique + timeline MTTD/MTTR → **après**.
5. `attacks/reset.sh` entre deux prises.

> Le clip doit tenir en **≤ 60 s sans coupe** : répéter la séquence jusqu'à ce que MTTD+MTTR tiennent dans la fenêtre.
