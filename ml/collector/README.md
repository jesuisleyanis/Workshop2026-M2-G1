# ml/collector

Service FastAPI (port interne **8004**, réseau `app`) qui construit le vecteur de features depuis l'API Prometheus.

## Configuration

| Variable | Défaut | Rôle |
|---|---|---|
| `PROMETHEUS_URL` | `http://prometheus:9090` | API Prometheus |
| `COLLECT_INTERVAL_SECONDS` | `15` | période de collecte |
| `PROM_RATE_WINDOW` | `30s` | fenêtre des `rate()` — doit contenir >= 2 scrapes (scrape 15 s -> 30 s) |

## Requêtes PromQL (`collector.build_queries`)

| Feature | Requête (fenêtre `W`) |
|---|---|
| `req_per_s` | `sum(rate(resilience_http_requests_total[W]))` |
| `p95_latency_ms` | `1000 * histogram_quantile(0.95, sum by (le)(rate(resilience_http_request_duration_seconds_bucket[W])))` |
| `ratio_4xx` / `ratio_5xx` | `sum(rate(...{status=~"4.."}[W])) / sum(rate(...[W]))` (idem `5..`) |
| `auth_failed_per_s` | `sum(rate(resilience_auth_logins_total{result="failed"}[W]))` |
| `waf_blocked_per_s` | `sum(rate(resilience_waf_blocked_total[W]))` |
| `cpu_pct_max` | `100 * max(rate(container_cpu_usage_seconds_total{name!=""}[W]))` (cAdvisor) |
| `mem_pct_max` | `100 * max(container_memory_working_set_bytes / (container_spec_memory_limit_bytes > 0))` |
| `db_errors_per_s` | `sum(rate(resilience_db_errors_total[W]))` |

Prérequis : `status` non groupé (`should_group_status_codes=False`, déjà le cas dans `resilience_common.metrics.instrument`).

## API

- `GET /api/v1/features` -> `{"feature_names": [...], "vector": [...], "ts": "...Z", "missing": [...], "window_seconds": 15}` ; **503** `{"error": {...}}` si pas de donnée fraîche.
- `GET /health` (liveness), `GET /ready` (200 seulement si une collecte récente a réussi), `GET /metrics`.

## Lancer / tester

```bash
uvicorn ml.collector.app:create_app --factory --port 8004     # depuis la racine du dépôt
cd ml && python -m pytest collector                            # Prometheus simulé (httpx.MockTransport)
docker build -f ml/collector/Dockerfile -t resilience/collector .   # depuis la racine
```
