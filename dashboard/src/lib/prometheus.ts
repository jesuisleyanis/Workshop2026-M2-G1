import type { ServiceHealth, StreamMessage } from '../types/events'
import { DEFAULT_THRESHOLD } from './state'

/**
 * Lecture du score ML et de la santé des services dans Prometheus (API instantanée
 * `GET /api/v1/query`). Le moteur de remédiation n'émet ni `score` ni `health` : ces deux
 * kinds internes sont produits ici, à partir des métriques du contrat §2.
 */

export const SCORE_QUERY = 'resilience_anomaly_score'
export const UP_QUERY = 'up'

/** job Prometheus (infra/prometheus/prometheus.yml) -> nom de service affiché. */
export const JOB_TO_SERVICE: Record<string, string> = {
  'payment-api': 'payment-api',
  auth: 'auth',
  detector: 'detector',
  remediation: 'remediation',
  'waf-exporter': 'waf',
  postgres: 'postgres',
}

type Obj = Record<string, unknown>
const isObj = (v: unknown): v is Obj => typeof v === 'object' && v !== null && !Array.isArray(v)

interface Sample {
  metric: Record<string, string>
  value: number
  ts: string
}

/** Extrait les séries d'une réponse `{"status":"success","data":{"resultType":"vector","result":[...]}}`. */
export function vectorSamples(raw: unknown): Sample[] {
  if (!isObj(raw) || raw.status !== 'success' || !isObj(raw.data) || !Array.isArray(raw.data.result)) return []
  const out: Sample[] = []
  for (const r of raw.data.result) {
    if (!isObj(r) || !isObj(r.metric) || !Array.isArray(r.value) || r.value.length !== 2) continue
    const [t, v] = r.value as [unknown, unknown]
    const value = Number(v)
    const seconds = Number(t)
    if (!Number.isFinite(value) || !Number.isFinite(seconds)) continue
    const metric: Record<string, string> = {}
    for (const [k, val] of Object.entries(r.metric)) if (typeof val === 'string') metric[k] = val
    out.push({ metric, value, ts: new Date(seconds * 1000).toISOString() })
  }
  return out
}

/** `resilience_anomaly_score{service}` -> un message `score` par service. */
export function scoreMessages(raw: unknown, threshold = DEFAULT_THRESHOLD): StreamMessage[] {
  return vectorSamples(raw)
    .filter((s) => s.value >= 0 && s.value <= 1)
    .map((s) => ({ kind: 'score', ts: s.ts, service: s.metric.service ?? 'payment-api', score: s.value, threshold }))
}

/** `up{job}` -> un message `health` (fusionné par nom dans l'état). Jobs inconnus ignorés. */
export function healthMessage(raw: unknown): StreamMessage | null {
  const services: ServiceHealth[] = []
  let ts = ''
  for (const s of vectorSamples(raw)) {
    const name = JOB_TO_SERVICE[s.metric.job ?? '']
    if (!name) continue
    ts = ts || s.ts
    services.push({ name, status: s.value === 1 ? 'up' : 'down', detail: s.value === 1 ? undefined : 'cible Prometheus injoignable' })
  }
  return services.length ? { kind: 'health', ts: ts || new Date().toISOString(), services } : null
}

export const queryUrl = (base: string, query: string): string => `${base}/api/v1/query?query=${encodeURIComponent(query)}`
