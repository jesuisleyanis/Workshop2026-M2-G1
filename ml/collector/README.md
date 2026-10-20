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
| `auth_failed_per_s` | `(sum(rate(resilience_auth_logins_total{result="failed"}[W])) or vector(0)) + (sum(rate(resilience_auth_rate_limited_total[W])) or vector(0))` — échecs **et** refus du rate-limit (sinon une force brute retombe à ~0 dès les 429) |
| `waf_blocked_per_s` | `sum(rate(resilience_waf_blocked_total[W]))` |
| `cpu_pct_max` | `100 * max(rate(container_cpu_usage_seconds_total{P}[W]))` (cAdvisor) ; `P` = `container_label_com_docker_compose_service=~"waf\|front\|payment-api\|auth\|postgres"` : services de la plateforme seulement |
| `mem_pct_max` | `100 * max(container_memory_working_set_bytes{P} / (container_spec_memory_limit_bytes{P} > 0))` — sans `P`, cAdvisor (92 % de sa limite) tenait la feature à 91-99 % en continu |
| `db_errors_per_s` | `sum(rate(resilience_db_errors_total[W]))` |

Prérequis : `status` non groupé (`should_group_status_codes=False`, déjà le cas dans `resilience_common.metrics.instrument`).

## API

- `GET /api/v1/features` -> `{"feature_names": [...], "vector": [...], "ts": "...Z", "missing": [...], "window_seconds": 15}` ; **503** `{"error": {...}}` si pas de donnée fraîche.
- `GET /health` (liveness), `GET /ready` (200 seulement si une collecte récente a réussi), `GET /metrics`.

## Capture de séries réelles (`capture.py`, pour ré-entraîner le modèle)

Rejoue **les mêmes requêtes** (`build_queries`, même fenêtre) sur une période passée via `/api/v1/query_range` et écrit un CSV
de fenêtres (`ml/shared/csvio.py`), mêmes règles de trous que la collecte temps réel (absent/NaN -> 0.0 + `missing`, fenêtre
vide ignorée). Lancée dans le conteneur (seul à joindre Prometheus) ; `--window`/`--step` valent par défaut
`PROM_RATE_WINDOW`/`COLLECT_INTERVAL_SECONDS` du conteneur.

```bash
docker compose -f infra/compose/docker-compose.yml exec -T collector \
  python -m ml.collector.capture --last 60m --label normal > ml/training/data/baseline_real.csv
# ou --start/--end ISO 8601 UTC, --label <scenario>, --no-header pour concaténer (>>)
```

Cibles `make capture-baseline` / `make capture-attack SC=...` : voir `ml/training/README.md` §6.

## Lancer / tester

```bash
uvicorn ml.collector.app:create_app --factory --port 8004     # depuis la racine du dépôt
cd ml && python -m pytest collector                            # Prometheus simulé (httpx.MockTransport), capture comprise
docker build -f ml/collector/Dockerfile -t resilience/collector .   # depuis la racine
```
