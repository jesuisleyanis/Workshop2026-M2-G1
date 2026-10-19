# Cahier des charges — ml/collector

**Pourquoi.** Le detector a besoin, toutes les 15 s, du vecteur de 9 features de `contracts.md §2`. Le collector isole la
connaissance de Prometheus (PromQL, cAdvisor) du reste de la chaîne ML.

**Périmètre.**
- Une requête PromQL instantanée par feature (cf. README), toutes les `COLLECT_INTERVAL_SECONDS` (15 s).
- Vecteur construit via `ml.shared.features` (ordre garanti), conservé en mémoire, exposé par `GET /api/v1/features`.
- `GET /health`, `GET /ready`, `GET /metrics` (métriques HTTP standard + `resilience_collector_*`), logs JSON (`get_logger`).
- Image durcie : slim, non-root (uid 10004), healthcheck.

**Absence de données (exigence).**
| Cas | Comportement |
|---|---|
| Prometheus injoignable / erreur HTTP | collecte en échec, ancien vecteur **périmé après 3 intervalles**, `/features` et `/ready` répondent 503 |
| Une feature sans série (ex. aucun trafic, 0/0 = NaN) | valeur `0.0`, feature listée dans `missing` |
| Aucune des 9 features | pas de snapshot (jamais un vecteur de zéros pris pour du trafic normal) |

**Sécurité.** Aucun secret, accès en lecture seule à Prometheus, réseau `app` interne uniquement, aucun port publié.

**Limites.** État en mémoire (un seul réplica) ; fenêtre `rate()` de 30 s par défaut (cf. README) ; `cpu/mem_pct_max`
supposent cAdvisor et des limites mémoire définies dans le compose.
