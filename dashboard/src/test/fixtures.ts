import type { EventSourceFactory, EventSourceLike } from '../hooks/useRemediationStream'

/** Exemple verbatim de docs/contracts.md §3. */
export const CONTRACT_ANOMALY_EVENT = {
  schema_version: '1.0',
  event_id: '6f0c2d3a-1b2c-4d5e-8f90-a1b2c3d4e5f6',
  ts: '2026-10-21T09:14:35.000Z',
  source: 'detector',
  service: 'payment-api',
  anomaly_score: 0.87,
  threshold: 0.6,
  incident_type: 'service_flood',
  features_top: [
    { name: 'req_per_s', value: 420.0, z: 9.2 },
    { name: 'ratio_5xx', value: 0.34, z: 7.1 },
  ],
  evidence: {
    prometheus_query: 'rate(resilience_http_requests_total[1m])',
    loki_query: '{service="payment-api"} |= "db_error"',
  },
}

export const INCIDENT_ID = 'inc-001'
const T = (s: number) => new Date(Date.parse('2026-10-21T09:14:35.000Z') + s * 1000).toISOString()

/** Séquence SSE complète d'un incident service_flood résolu : [nom d'événement, données]. */
export const FULL_SEQUENCE: [string, unknown][] = [
  ['anomaly_detected', { ...CONTRACT_ANOMALY_EVENT, incident_id: INCIDENT_ID }],
  [
    'remediation_started',
    {
      ts: T(2),
      incident_id: INCIDENT_ID,
      incident_type: 'service_flood',
      service: 'payment-api',
      actions: [{ type: 'waf_block_ip', params: { source: 'from_event' } }, { type: 'restart_service', params: { service: 'payment-api' } }],
      dry_run: false,
    },
  ],
  ['remediation_action', { ts: T(3.5), incident_id: INCIDENT_ID, action: 'waf_block_ip', result: 'ok' }],
  ['remediation_action', { ts: T(5), incident_id: INCIDENT_ID, action: 'restart_service', result: 'ok' }],
  [
    'remediation_verified',
    {
      ts: T(9),
      incident_id: INCIDENT_ID,
      mttd_seconds: 4.2,
      mttr_seconds: 9.0,
      verify_tx: { ok: true, tx_id: 'tx-verify-42', ts: T(9), duration_ms: 87 },
    },
  ],
]

/** EventSource factice : permet d'émettre des événements SSE depuis le test. */
export class FakeEventSource implements EventSourceLike {
  static last: FakeEventSource | null = null
  readyState = 0
  onopen: ((ev: Event) => void) | null = null
  onerror: ((ev: Event) => void) | null = null
  closed = false
  private listeners = new Map<string, ((ev: MessageEvent) => void)[]>()

  constructor(public url: string) {
    FakeEventSource.last = this
  }
  addEventListener(type: string, listener: (ev: MessageEvent) => void) {
    this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener])
  }
  close() {
    this.closed = true
    this.readyState = 2
  }
  open() {
    this.readyState = 1
    this.onopen?.(new Event('open'))
  }
  error(closed = false) {
    this.readyState = closed ? 2 : 0
    this.onerror?.(new Event('error'))
  }
  emit(name: string, data: unknown) {
    const payload = typeof data === 'string' ? data : JSON.stringify(data)
    for (const l of this.listeners.get(name) ?? []) l(new MessageEvent(name, { data: payload }))
  }
}

export const fakeFactory: EventSourceFactory = (url) => new FakeEventSource(url)
