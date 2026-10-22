# infra/grafana — supervision Grafana (R7, R12)

Tout est **provisionné en code** (montage `../grafana/provisioning:/etc/grafana/provisioning:ro`) :

| Dossier | Contenu |
|---|---|
| `provisioning/datasources/` | Prometheus (`uid: prometheus`, défaut) et Loki (`uid: loki`) |
| `provisioning/alerting/` | 4 règles SOC (auth_abuse, service_flood, web_attack, data_corruption) — voir `README-SOC.md` |
| `provisioning/dashboards/` | provider `dashboards.yml` + dashboard `resilience-overview.json` |

## Dashboard « RESILIENCE-ALPHA — Supervision SOC »

`uid: resilience-overview`, dossier `RESILIENCE-ALPHA`, **page d'accueil** de Grafana
(`GF_DASHBOARDS_DEFAULT_HOME_DASHBOARD_PATH` dans le compose). Rafraîchi toutes les 10 s, 30 min par défaut.

| Rangée | Ce qu'on y lit |
|---|---|
| Vue d'ensemble | score ML vs seuil, cibles DOWN, req/s, % 5xx, alertes SOC actives, blocages WAF, MTTD/MTTR moyens, actions de remédiation, transactions/min, échecs de login/min, visages enrôlés, UP/DOWN par cible |
| Détection ML & remédiation | courbe du score (seuil en pointillé), actions par type/résultat, tableau MTTD/MTTR par incident, journal detector + remédiation |
| Trafic applicatif | débit par service, classes 2xx/4xx/5xx, latence p95, transactions, erreurs DB, top endpoints |
| Sécurité & SOC | logins/rate-limit, blocages WAF par règle CRS, état des règles SOC, top IP bloquées (Loki), journal sécurité |
| Back-office & visage | vérifications 1:1, latence p95, étape visage + verrouillages, publications LED MQTT, journal |
| Infrastructure | CPU/mémoire par conteneur (cAdvisor, profil `full`), réseau du WAF, PostgreSQL (pg-exporter) |
| Journaux | volume par service, warnings/erreurs, explorateur filtré par la variable `Service (logs)` |

Annotations rouges : événements Loki `anomaly_detected`, `remediation_started|verified|failed`.

- Le **seuil** du score est celui de `ml/training/data/calibration.json` (test : il doit y être égal). Après un
  `make calibrate`, reporter la nouvelle valeur dans le JSON (2 panneaux).
- Les panneaux MTTD/MTTR, actions et transactions affichent « aucun incident / aucune donnée » tant qu'aucun
  événement n'a eu lieu : les compteurs Prometheus à labels n'existent qu'après leur premier incrément.
- `allowUiUpdates: false` : on modifie le **JSON versionné** (ou on exporte depuis l'UI puis on remplace le fichier),
  jamais directement dans Grafana.

## Accès

Grafana n'est sur aucun réseau publié (`obs` est `internal`, pas de `ports:`) : accès par tunnel local lié à
`127.0.0.1` uniquement (`docs/network.md`). Sous Windows, le port 3000 est souvent dans une plage réservée par
Hyper-V (`netsh int ipv4 show excludedportrange protocol=tcp`) : utiliser un autre port local (ex. 3300).
Identifiant `admin`, mot de passe `GRAFANA_PASSWORD` (SOPS → `.env`).

## Tests

```bash
python -m pytest -q infra/tests/test_grafana_dashboards.py infra/tests/test_soc_rules.py
```

`test_grafana_dashboards.py` : provider dans le volume monté, page d'accueil, datasources provisionnées,
métriques `resilience_*` déclarées au contrat (§2), signaux des 5 temps de la démo présents, seuil = calibration,
grille sans chevauchement, aucun double axe Y.
