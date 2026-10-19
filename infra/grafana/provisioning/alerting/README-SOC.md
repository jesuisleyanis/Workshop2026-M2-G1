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

## Routage vers la remédiation — I6 **fermé** (ticket #13)

Choix acté : **voie Prometheus + Alertmanager** (pas de contact point Grafana). Grafana reste
l'affichage SOC ; le routage est porté par la chaîne standard Prometheus → Alertmanager → webhook.

```
infra/prometheus/rules/soc.yml  ──(rule_files, miroir des règles Grafana)──►  Prometheus
   ──(alerting.alertmanagers)──►  Alertmanager (profil `full`, réseaux obs+app)
   ──POST /events/alertmanager, Authorization: Bearer <secret remediation_token>──►  moteur de remédiation
   ──remediation/alertmanager.py (webhook → AnomalyEvent §3)──►  engine.handle_event (mêmes garde-fous que /events)
```

| Maillon | Fichier | Détail |
|---|---|---|
| Règles Prometheus | `infra/prometheus/rules/soc.yml` | 4 alertes (`SocAuthAbuse`, `SocServiceFlood`, `SocWafBlocks`, `SocDataCorruption`), **mêmes expressions/seuils/`for`** que `soc-rules.yml` ; labels `incident_type` + `service`, annotations `expr`/`value`/`feature` (reprises dans `evidence` / `features_top`). Cohérence Grafana ⇔ Prometheus vérifiée par `infra/tests/test_soc_rules.py`. |
| Prometheus | `infra/prometheus/prometheus.yml` | `rule_files: /etc/prometheus/rules/*.yml` (monté par Compose) + `alerting.alertmanagers → alertmanager:9093`. |
| Alertmanager | `infra/alertmanager/alertmanager.yml` | Route unique → webhook `http://remediation:8005/events/alertmanager`, `send_resolved: false`, **`authorization: Bearer` via `credentials_file: /run/secrets/remediation_token`** (secret Compose alimenté par `REMEDIATION_TOKEN` du `.env` SOPS — jamais en clair dans le YAML versionné). `group_by: [incident_type, service]`, `repeat_interval: 5m`. |
| Moteur | `remediation/alertmanager.py`, `POST /events/alertmanager` | Alerte `firing` + `incident_type` de l'énumération → `AnomalyEvent` (`source: alertmanager`, score/seuil 1.0, `event_id` = uuid5(fingerprint, startsAt) ⇒ les ré-émissions sont **rejouées idempotemment**). Alertes résolues / sans `incident_type` / inconnues : ignorées (`skipped`), jamais mappées sur `unknown`. Aucune route d'injection non authentifiée (401 sans Bearer). |

Conséquences :

- **Le détecteur ML reste le chemin principal** ; le SOC est complémentaire. Si les deux déclenchent
  sur le même `incident_type:service`, le moteur dédoublonne (incident actif → `duplicate`, puis `cooldown`).
- Alertmanager est dans le profil `full` (`make up-full`). En profil `demo`, Prometheus évalue les règles
  (visibles dans son UI) mais ne peut pas joindre Alertmanager : erreurs de résolution DNS journalisées,
  sans effet sur la démo.
- Les règles SOC sont des agrégats : pas de label `source_ip`. Les actions `waf_block_ip` échouent
  proprement (« aucune IP source ») et la règle enchaîne sur l'action suivante (restart, rate-limit, restore).

## Validation

- Hors stack : `python -m pytest infra/tests/test_soc_rules.py -q` (contrat statique).
- En live (`make up-full`) : déclencher un scénario (`attacks/run.sh ...`), vérifier que l'alerte
  passe en `Firing` (Grafana → Alerting, Prometheus → Alerts), qu'Alertmanager la notifie (UI :9093,
  réseau `obs`) et que le moteur journalise un incident `source: alertmanager`
  (`GET /incidents`, ou `docker compose logs remediation | grep alertmanager`).
- Hors stack, le webhook lui-même : `cd remediation && pytest tests/test_alertmanager.py -q` (13 tests).
