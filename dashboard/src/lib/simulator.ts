import type { EventSourceLike } from '../hooks/useRemediationStream'
import { DEFAULT_SERVICES, PLAYBOOKS } from './state'

/**
 * Simulation locale du flux SSE (répétition / flux injoignable). Émet les MÊMES trames JSON
 * que le moteur (contrat §3 + enveloppe du CDC) : elles passent par parseStreamMessage comme
 * le flux réel. Toujours signalée à l'écran : ce n'est jamais présenté comme le flux réel.
 */

export const SIMULATED_TYPES = ['service_flood', 'auth_abuse', 'data_corruption'] as const
export type SimulatedType = (typeof SIMULATED_TYPES)[number]

const SCORED = ['payment-api', 'auth', 'postgres']
const TARGET: Record<SimulatedType, string> = { service_flood: 'payment-api', auth_abuse: 'auth', data_corruption: 'postgres' }
const PARAMS: Record<string, Record<string, unknown>> = {
  waf_block_ip: { source: 'from_event' },
  restart_service: { service: 'payment-api' },
  tighten_rate_limit: { service: 'auth', factor: 0.5 },
  restore_pg_dump: { backup: 'latest' },
}
const FEATURES: Record<SimulatedType, [string, number, number][]> = {
  service_flood: [['req_per_s', 1840, 6.4], ['ratio_5xx', 0.31, 4.1], ['latency_p95_ms', 2350, 3.7], ['open_connections', 912, 2.9]],
  auth_abuse: [['login_failures_per_min', 420, 7.2], ['distinct_users_per_ip', 96, 5.5], ['ratio_401', 0.78, 4.4], ['token_issue_rate', 3, -1.8]],
  data_corruption: [['checksum_mismatch', 214, 8.1], ['tx_reject_ratio', 0.44, 5.0], ['row_updates_unusual', 12500, 3.9], ['ledger_drift_cents', 1834250, 3.2]],
}

const BASE_SCORE = 0.16
const THRESHOLD = 0.6
const iso = () => new Date().toISOString()
const rid = () => Math.random().toString(36).slice(2, 10)

export class SimulatedEventSource implements EventSourceLike {
  readyState = 0
  onopen: ((ev: Event) => void) | null = null
  onerror: ((ev: Event) => void) | null = null
  private listeners = new Map<string, ((ev: MessageEvent) => void)[]>()
  private intervals: ReturnType<typeof setInterval>[] = []
  private timeouts: ReturnType<typeof setTimeout>[] = []
  private boost: Record<string, number> = {}
  private status: Record<string, string> = Object.fromEntries(DEFAULT_SERVICES.map((s) => [s.name, 'up']))
  private busy = false

  constructor() {
    // Ouverture asynchrone, comme un vrai EventSource (les écouteurs sont posés entre-temps).
    this.timeouts.push(setTimeout(() => this.start(), 0))
  }

  addEventListener(type: string, listener: (ev: MessageEvent) => void): void {
    this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener])
  }

  close(): void {
    this.readyState = 2
    this.intervals.forEach(clearInterval)
    this.timeouts.forEach(clearTimeout)
    this.intervals = []
    this.timeouts = []
  }

  get running(): boolean {
    return this.busy
  }

  /** Joue un incident complet : détection -> décision -> actions -> vérification. */
  trigger(type: SimulatedType): boolean {
    if (this.busy || this.readyState === 2) return false
    this.busy = true
    const svc = TARGET[type]
    const incident_id = `SIM-${rid().slice(0, 4).toUpperCase()}`
    const plan = PLAYBOOKS.find((p) => p.type === type)!.actions
    const t0 = Date.now()
    let detectedAt = t0

    this.at(0, () => (this.boost[svc] = 0.25))
    this.at(1000, () => {
      this.boost[svc] = 0.5
      this.status[svc] = 'degraded'
      this.health()
    })
    this.at(2200, () => {
      this.boost[svc] = 0.68
      detectedAt = Date.now()
      this.emit('anomaly_detected', {
        schema_version: '1.0',
        event_id: `evt-${rid()}`,
        incident_id,
        ts: iso(),
        source: 'detector',
        service: svc,
        anomaly_score: 0.87,
        threshold: THRESHOLD,
        incident_type: type,
        features_top: FEATURES[type].map(([name, value, z]) => ({ name, value, z })),
        evidence: {
          prometheus_query: `rate(resilience_http_requests_total{service="${svc}"}[1m])`,
          loki_query: `{service="${svc}"} |= "error"`,
        },
      })
    })
    this.at(3400, () =>
      this.emit('remediation_started', {
        ts: iso(),
        incident_id,
        incident_type: type,
        service: svc,
        dry_run: false,
        actions: plan.map((a) => ({ type: a, params: PARAMS[a] ?? {} })),
      }),
    )
    let t = 3400
    for (const a of plan) {
      t += 1800
      if (a === 'restart_service' || a === 'restore_pg_dump') {
        this.at(t - 1200, () => {
          this.status[svc] = 'down'
          this.health()
        })
      }
      this.at(t, () => {
        if (a === 'waf_block_ip') this.boost[svc] = 0.35
        const detail = Object.entries(PARAMS[a] ?? {}).map(([k, v]) => `${k}=${String(v)}`).join(' ')
        this.emit('remediation_action', { ts: iso(), incident_id, action: a, result: 'ok', detail: detail || undefined, attempt: 1 })
      })
    }
    this.at(t + 600, () => {
      this.boost[svc] = 0
      this.status[svc] = 'up'
      this.health()
    })
    this.at(t + 1600, () => {
      const now = Date.now()
      this.emit('remediation_verified', {
        ts: iso(),
        incident_id,
        mttd_seconds: Number(((detectedAt - t0) / 1000).toFixed(1)),
        mttr_seconds: Number(((now - detectedAt) / 1000).toFixed(1)),
        verify_tx: { ok: true, tx_id: `verify-${rid()}`, ts: iso(), duration_ms: 130 + Math.round(Math.random() * 60) },
      })
      this.busy = false
    })
    return true
  }

  private start() {
    if (this.readyState === 2) return
    this.readyState = 1
    this.onopen?.(new Event('open'))
    // Amorce : 60 s d'historique nominal pour que la courbe ne parte pas de zéro.
    const now = Date.now()
    for (let i = 60; i > 0; i--) {
      for (const svc of SCORED) this.emitScore(svc, new Date(now - i * 1000).toISOString())
    }
    this.tick()
    this.health()
    this.verifyTx()
    this.intervals.push(setInterval(() => this.tick(), 1000), setInterval(() => this.health(), 3000), setInterval(() => this.verifyTx(), 5000))
  }

  private at(ms: number, fn: () => void) {
    this.timeouts.push(setTimeout(fn, ms))
  }

  private tick() {
    for (const svc of SCORED) this.emitScore(svc, iso())
  }

  private emitScore(svc: string, ts: string) {
    const v = BASE_SCORE + Math.random() * 0.1 + (this.boost[svc] ?? 0)
    this.emit('score', { ts, service: svc, anomaly_score: Math.min(0.99, Math.max(0.02, v)), threshold: THRESHOLD })
  }

  private health() {
    this.emit('health', { ts: iso(), services: Object.entries(this.status).map(([name, status]) => ({ name, status })) })
  }

  private verifyTx() {
    if (this.busy) return
    this.emit('verify_tx', { ts: iso(), ok: true, tx_id: `verify-${rid()}`, duration_ms: 110 + Math.round(Math.random() * 90) })
  }

  private emit(name: string, data: unknown) {
    const ev = new MessageEvent(name, { data: JSON.stringify(data) })
    for (const l of this.listeners.get(name) ?? []) l(ev)
  }
}
