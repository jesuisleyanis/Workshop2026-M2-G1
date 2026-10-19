# ml/shared

Source de vérité du vecteur de features (`docs/contracts.md §2`).

```python
from ml.shared.features import FEATURE_NAMES, vector_from_dict, zscores, classify_incident
```

Ordre figé : `req_per_s, p95_latency_ms, ratio_4xx, ratio_5xx, auth_failed_per_s, waf_blocked_per_s, cpu_pct_max, mem_pct_max, db_errors_per_s`.

## Règles de `classify_incident(z)` (heuristique de routage, pas la détection)

Entrée : z-scores par feature. Seuls les écarts vers le haut comptent. Le groupe au z le plus élevé gagne s'il dépasse `SIGNAL_Z_MIN = 3`.

| Type | Signal dominant |
|---|---|
| `data_corruption` | `db_errors_per_s` |
| `auth_abuse` | `auth_failed_per_s` |
| `web_attack` | `waf_blocked_per_s` |
| `service_flood` | `req_per_s`, ou (`p95_latency_ms` ET `ratio_5xx`) **si** les erreurs DB ne sont pas dominantes |
| `unknown` | aucun groupe >= 3 |

La clause sur les erreurs DB évite de prendre une corruption (5xx + latence en cascade) pour un problème de disponibilité.

Tests : `cd ml && python -m pytest shared`.
