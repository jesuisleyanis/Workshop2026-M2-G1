# Fonction SOC (R12) — règles, couverture et routage

Fonction SOC intégrée à la supervision : des règles de corrélation métriques/logs
détectent des comportements suspects, **en complément** du détecteur ML. Décision
d'équipe (ADR, ROADMAP) : SOC = règles Grafana/Loki, pas de Wazuh par défaut.

## Règles livrées (`soc-rules.yml`)

| uid | incident_type | Signal (PromQL) | Seuil |
|---|---|---|---|
| `soc-auth-abuse` | `auth_abuse` | `rate(resilience_auth_logins_total{result="failed"}[1m])` | > 5/s |
| `soc-service-flood` | `service_flood` | `rate(resilience_http_requests_total{service="payment-api",status=~"5.."}[1m])` | > 2/s |
| `soc-waf-blocks` | `web_attack` | `rate(resilience_waf_blocked_total[1m])` | > 1/s |
| `soc-data-corruption` | `data_corruption` | `rate(resilience_db_errors_total[1m])` | > 0 |

Couverture : **les 4 `incident_type`** de `remediation/decision_table.yml` ont une règle SOC
correspondante (vérifié par `infra/tests/test_soc_rules.py`). Chaque règle porte le label
`incident_type` exploitable par le relais de remédiation.

## Corrections apportées (sinon les règles ne s'évaluent pas)

- **`uid` de datasource** ajouté dans `datasources/datasources.yml` (`prometheus`, `loki`) :
  les règles référencent `datasourceUid: prometheus` ; sans `uid` fixe, Grafana en génère
  un aléatoire et les règles échouent (« datasource not found »).
- **Étape de réduction** `B (reduce last)` entre la requête `A` et le seuil `C` : l'évaluateur
  de seuil refuse une série temporelle non réduite.
- Champs d'alerting unifié complétés : `for`, `noDataState`, `execErrState`, `relativeTimeRange`.

## ⚠️ Routage vers la remédiation — POINT D'INTÉGRATION OUVERT

À ce jour, une alerte SOC **s'affiche dans Grafana mais n'atteint PAS le moteur de
remédiation**. Deux maillons manquent, hors du périmètre « règles SOC » :

1. **Côté remédiation (leur contrat) :** `infra/alertmanager/alertmanager.yml` poste vers
   `http://remediation:8005/events/alertmanager`, mais **cet endpoint n'existe pas** dans le
   moteur (seul `POST /events` au format AnomalyEvent est exposé). Il faut un adaptateur
   Alertmanager→AnomalyEvent côté `remediation/`.
2. **Côté infra (leur fichier) :** au choix —
   - *voie Prometheus+Alertmanager* : `prometheus.yml` n'a ni `rule_files` ni bloc
     `alerting.alertmanagers` → Alertmanager ne reçoit rien. (Les règles SOC devraient alors
     exister aussi en format Prometheus, ou Grafana doit pousser vers l'Alertmanager externe.)
   - *voie Grafana native* : provisionner un **contact point** + une **notification policy**
     (filtrés sur le label `incident_type`) vers le moteur.

Le détecteur ML reste le chemin principal de déclenchement de la remédiation (contrat §3) ;
le SOC est le chemin complémentaire. Ces deux maillons sont suivis dans la ROADMAP
(points d'intégration) et à trancher avec les référents **remédiation** et **infra**.

## Validation

- Hors stack : `python -m pytest infra/tests/test_soc_rules.py -q` (contrat statique).
- En live : lever la stack, déclencher un scénario (`attacks/run.sh ...`), vérifier que
  l'alerte passe en `Firing` dans Grafana (Alerting → rules) et que le label `incident_type`
  est correct.
