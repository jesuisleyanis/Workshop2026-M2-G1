# Commandes — lancer, entraîner, tester, démontrer

Référence opérationnelle de toutes les façons de lancer RESILIENCE-ALPHA. Source de vérité des cibles :
[`Makefile`](../Makefile) (`make help`). Procédures détaillées : [`scripts/README.md`](../scripts/README.md),
[`ml/training/README.md`](../ml/training/README.md), [`attacks/README.md`](../attacks/README.md).

> **Windows** : toutes les commandes `make` se lancent depuis **Git Bash** (`winget install ezwinports.make`).
> Docker Desktop (WSL2) doit être démarré.

> Toutes les cibles `make` passent `--env-file .env` à Compose et lèvent le profil `ml` (détection).
> Historique des correctifs : [`plan-optimisation-lancement.md`](plan-optimisation-lancement.md).

---

## 0. Une seule fois par poste

| Étape | Commande | Effet |
|---|---|---|
| Clé age | voir [`security/sops/README.md`](../security/sops/README.md) | clé privée hors git, requise pour déchiffrer |
| Secrets | `make decrypt` | `security/sops/secrets.enc.env` → `.env` (non commité, `chmod 600`) |
| Docker BuildKit | actif par défaut (Docker Desktop ≥ 23) — requis pour le cache pip des builds | |
| Deps tests Python | voir [README § Tests](../README.md#tests) | venv 3.12 avec toutes les libs (uniquement pour `make test`) |
| Deps tests front | `cd services/front && npm ci` puis `cd dashboard && npm ci` | uniquement pour `make test-front` |

Aucun Python ML n'est requis sur le poste : l'entraînement tourne dans Docker (§4).

---

## 1. Profils Docker Compose

Fichier : `infra/compose/docker-compose.yml`. Un service **sans** `profiles:` démarre toujours.

| Profil | Services | Quand |
|---|---|---|
| *(aucun)* — appelé `demo` dans le Makefile | waf, waf-exporter, front, payment-api, auth, postgres, docker-socket-proxy, remediation, dashboard, prometheus, loki, promtail, grafana | toujours |
| `ml` | collector, detector | **détection** — indispensable à la boucle Zero-Touch |
| `full` | alertmanager, cadvisor, pg-exporter | observabilité complète, règles SOC, captures ML |
| `iot` | mosquitto (publie 1883 sur le hotspot) | démo LED ESP8266 |
| `ai` | ollama, assistant | assistant RAG opérateur |
| `attack` | attacker (curl) | banc d'essai local |

Le Makefile regroupe les profils : `PROFILES_DEMO` = *(aucun)* + `ml` ; `PROFILES_FULL` = + `full` ;
`PROFILES_ALL` = tous (pour `ps` / `down`).

Raccourci pour les commandes Compose directes ci-dessous :

```bash
COMPOSE="docker compose -f infra/compose/docker-compose.yml --env-file .env"
```

---

## 2. Lancer le projet

| Besoin | Commande | Rebuild ? |
|---|---|---|
| **Premier lancement / après un pull** — démo (chemin critique + détection ML) | `make up` | oui |
| Idem + observabilité complète (Alertmanager, cAdvisor, pg-exporter) | `make up-full` | oui |
| Idem démo + broker MQTT (PC Hôte, hotspot actif) | `make up-iot` | oui |
| **Relance quotidienne** (images déjà construites, quelques secondes) | `make start` / `make start-full` | non |
| Construire les images sans rien lancer | `make build` | oui |
| + assistant RAG | `$COMPOSE --profile ai up -d --build` | oui |
| Données fictives | `make seed` (demo01…demo05, 1 000 € chacun, idempotent) | — |
| État des conteneurs (tous profils) | `make ps` | — |
| Logs d'un service | `$COMPOSE logs -f detector` | — |
| Arrêter / nettoyer (tous profils) | `make down` | — |
| Reconstruire un seul service | `$COMPOSE build payment-api && $COMPOSE up -d --no-deps payment-api` | ce service |

`make up*` déchiffre d'abord les secrets (`make decrypt`) et échoue clairement si `.env` est absent.
Les services démarrent dans l'ordre de santé : postgres *healthy* → payment-api/auth *healthy* → WAF, etc.

Accès : front via le WAF sur `https://localhost` (certificat auto-signé). Seul le WAF publie des ports HTTP ;
dashboard, Grafana et API internes ne sont pas publiés (voir [`dashboard/README.md`](../dashboard/README.md) pour une
publication `127.0.0.1` en dev).

---

## 3. Vérifier et démontrer

| Besoin | Commande | Résultat attendu |
|---|---|---|
| Transaction de contrôle | `make verify` | code `0` = OK |
| Démo 5 temps | `make demo SC=service_flood` | AVANT → ATTAQUE → DÉTECTION → REMÉDIATION → APRÈS |
| Scénario seul (dev) | `make attack SC=<scenario>` | `service_flood`, `auth_abuse`, `web_attack`, `data_corruption` |
| Kill-switch | `make stop-attack` | arrête tous les scénarios |
| Remettre la cible « avant » | `make reset` | |
| Audit de durcissement | `make audit` | |
| Archive du rendu | `make package` | `Workshop2026-M2-G1-Code.zip` sans secrets |

En démo notée, l'attaque part du **PC Attaquant** : [`attacks/RUNBOOK-PC-ATTAQUANT.md`](../attacks/RUNBOOK-PC-ATTAQUANT.md).

---

## 4. ML — entraîner uniquement

Tout tourne dans l'image `resilience/ml-tools` (étape du Dockerfile detector : même Python 3.12 et même
scikit-learn que le runtime → même `model_fingerprint`). Le dépôt est monté en `/src`, les artefacts sont écrits dans
`ml/training/artifacts/`.

### 4.1 Sans stack (données synthétiques ou CSV déjà capturés)

| Besoin | Commande |
|---|---|
| Construire l'image d'outils | `make ml-tools` |
| **Entraîner seulement** | `make train` |
| Entraîner une version précise | `make train VERSION=1.2.0` |
| Entraîner seulement si aucun artefact local | `make model` |
| Embarquer le modèle dans le detector (rebuild + relance du seul detector) | `make retrain-detector` |
| Calibrer le seuil (requiert `data/attacks_real.csv`) | `make calibrate` |
| Tests ML | `make test-ml` |
| Paramètres avancés | `MSYS_NO_PATHCONV=1 docker run --rm -v "$(pwd -W):/src" -w /src resilience/ml-tools python -m ml.training.train --n-estimators 300 --seed 7` |

`make train` n'a besoin ni de la stack ni de `.env`. Il écrit dans `ml/training/artifacts/` (aperçu, rapports) ;
**l'image du detector, elle, ré-entraîne au build** à partir des mêmes données — d'où `make retrain-detector`.
`make train` utilise automatiquement `ml/training/data/baseline_real.csv`, `attacks_real.csv` et `calibration.json`
s'ils existent, sinon la baseline synthétique.

### 4.2 Avec la stack (vraies séries Prometheus — procédure avant jury)

Prérequis : `make up-full` (Prometheus + cAdvisor + détection) et `make seed`.

```bash
make capture-baseline                      # 60 min de trafic légitime (DURATION=60m), detector arrêté pendant la capture
make capture-attack SC=service_flood       # puis auth_abuse, web_attack, data_corruption (ATTACK_S=20)
make calibrate                             # seuil + MTTD par scénario -> data/calibration.json
make train                                 # ré-entraîne avec la calibration (échec code 3 si empreinte différente)
make retrain-detector                      # le build du detector ré-entraîne avec ces données et le relance
```

Codes retour de `calibrate` : `0` OK · `1` non séparable · `2` MTTD > 20 s. Détails :
[`ml/training/README.md` §6](../ml/training/README.md).

### 4.3 Trafic légitime seul

`make traffic DURATION=10m` — fond de trafic réaliste (temps 1 de la démo, ou pour observer le score ML).

---

## 5. Tests

| Périmètre | Commande |
|---|---|
| Tout | `make test` |
| Python seul | `make test-py` (ou `make test-py PYTHON=.venv/Scripts/python` sous Windows) |
| Front + dashboard | `make test-front` |
| ML (Docker, rien à installer) | `make test-ml` |
| Un composant | `cd remediation && python -m pytest` |

---

## 6. Dépannage rapide

| Symptôme | Cause probable | Remède |
|---|---|---|
| Aucune détection pendant une attaque | detector arrêté ou *unhealthy* | `make ps`, `$COMPOSE logs detector` |
| `required variable … is missing a value` | `.env` incomplet (ancien déchiffrement) | comparer avec `security/sops/secrets.example.env`, compléter `secrets.enc.env`, `make decrypt` |
| `dependency failed to start` | une dépendance n'est jamais *healthy* (ex. postgres) | `$COMPOSE logs <service>` |
| `make verify` KO juste après `up` | services pas encore *healthy* ou base non seedée | attendre `ps` healthy, `make seed` |
| Build du detector échoue (code 3) | calibration périmée pour ce modèle | `make calibrate` |
| Attaque sans effet en capture | cible = IP du hotspot inactif | `ATTACK_TARGET=https://localhost` (défaut des captures) |
