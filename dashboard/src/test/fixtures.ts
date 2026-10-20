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

// --- Enveloppe RÉELLE du moteur : `event: timeline` ------------------------------------
// Trames produites par remediation/engine.py + timeline.py (capturées via le banc de test du
// moteur, ids/horodatages ré-échelonnés). C'est la forme que le dashboard reçoit en live.
export const ENGINE_INCIDENT_ID = 'ebbea902-167a-417e-97f4-eafb82d12cc7'
const frame = (id: number, s: number, phase: string, status: string, message: string, data: unknown, incident_type = 'service_flood', incident_id = ENGINE_INCIDENT_ID) => ({
  id,
  incident_id,
  incident_type,
  ts: T(s),
  phase,
  status,
  message,
  data,
})

/** service_flood : détection -> décision -> waf_block_ip (verify KO) -> restart_service (verify OK) -> clôture. */
export const ENGINE_TIMELINE: [string, unknown][] = [
  ['timeline', frame(1, 0, 'detection', 'info', 'Anomalie détectée sur payment-api : service_flood', { event_id: '3f3827f8-d3e5-4181-92e9-af8eb4341692', source: 'detector', anomaly_score: 0.87, threshold: 0.6, service: 'payment-api', features_top: [{ name: 'req_per_s', value: 420.0, z: 9.2 }] })],
  ['timeline', frame(2, 0.1, 'decision', 'info', 'Règle sélectionnée : waf_block_ip -> restart_service', { actions: [{ type: 'waf_block_ip', params: { source: 'from_event' } }, { type: 'restart_service', params: { service: 'payment-api' } }], verify: 'verify_tx', dry_run: false, max_attempts: 3, cooldown_seconds: 60 })],
  ['timeline', frame(3, 0.2, 'action', 'running', 'Action waf_block_ip en cours', { action: 'waf_block_ip', params: { source: 'from_event' }, attempt: 1 })],
  ['timeline', frame(4, 1.5, 'action', 'ok', 'waf_block_ip : 203.0.113.7 bloquée (temporary), WAF rechargé (1)', { action: 'waf_block_ip', attempt: 1, result: 'success', duration_ms: 1300, changed: true, ip: '203.0.113.7', list: 'temporary', reloaded: ['cid-waf'] })],
  ['timeline', frame(5, 2.0, 'verification', 'ko', 'verify_tx KO après waf_block_ip (essai 1/1)', { attempt: 1, try: 1, rc: 1, detail: 'verify_tx: service injoignable', after: 'waf_block_ip' })],
  ['timeline', frame(6, 2.1, 'action', 'running', 'Action restart_service en cours', { action: 'restart_service', params: { service: 'payment-api' }, attempt: 1 })],
  ['timeline', frame(7, 4.2, 'action', 'ok', 'restart_service : service payment-api redémarré (1 conteneur(s))', { action: 'restart_service', attempt: 1, result: 'success', duration_ms: 2100, changed: null, service: 'payment-api', containers: ['cid-payment-'] })],
  ['timeline', frame(8, 9.0, 'verification', 'ok', 'verify_tx OK après restart_service (essai 1/1)', { attempt: 1, try: 1, rc: 0, detail: 'verify_tx: OK — transaction fictive 42 créée', after: 'restart_service' })],
  ['timeline', frame(9, 9.0, 'closure', 'ok', 'Incident clos — service rétabli (MTTR 9.0s)', { mttd_seconds: 4.2, mttr_seconds: 9.0, attempts: 1 })],
]

export const ENGINE_ESCALATED_ID = 'a83992c2-423c-4abe-8cde-d9227fbf5020'
/** data_corruption : restore_pg_dump en échec -> notify_operator -> escalade (reste PENDANT). */
export const ENGINE_TIMELINE_ESCALATED: [string, unknown][] = [
  ['timeline', frame(101, 20, 'detection', 'info', 'Anomalie détectée sur postgres : data_corruption', { event_id: '2035fc31-3a4f-4838-b519-82a65c4ff0a4', source: 'detector', anomaly_score: 0.91, threshold: 0.6, service: 'postgres', features_top: [{ name: 'db_errors_per_s', value: 12.0, z: 8.0 }] }, 'data_corruption', ENGINE_ESCALATED_ID)],
  ['timeline', frame(102, 20.1, 'decision', 'info', 'Règle sélectionnée : restore_pg_dump', { actions: [{ type: 'restore_pg_dump', params: { backup: 'latest' } }], verify: 'verify_tx', dry_run: false, max_attempts: 1, cooldown_seconds: 60 }, 'data_corruption', ENGINE_ESCALATED_ID)],
  ['timeline', frame(103, 20.2, 'action', 'running', 'Action restore_pg_dump en cours', { action: 'restore_pg_dump', params: { backup: 'latest' }, attempt: 1 }, 'data_corruption', ENGINE_ESCALATED_ID)],
  ['timeline', frame(104, 22, 'action', 'failed', 'restore_pg_dump : playbook pg_restore.yml en échec (status=failed)', { action: 'restore_pg_dump', attempt: 1, result: 'failure', duration_ms: 1800, changed: null }, 'data_corruption', ENGINE_ESCALATED_ID)],
  ['timeline', frame(105, 22.1, 'action', 'running', 'Action notify_operator en cours', { action: 'notify_operator', params: {}, attempt: 1 }, 'data_corruption', ENGINE_ESCALATED_ID)],
  ['timeline', frame(106, 22.2, 'action', 'ok', 'notify_operator : opérateur notifié : verify_tx toujours KO après 1 tentative(s) : escalade (max_attempts)', { action: 'notify_operator', attempt: 1, result: 'success', duration_ms: 5, changed: null, reason: 'verify_tx toujours KO après 1 tentative(s) : escalade (max_attempts)' }, 'data_corruption', ENGINE_ESCALATED_ID)],
  ['timeline', frame(107, 22.3, 'escalation', 'failed', 'Escalade : verify_tx toujours KO après 1 tentative(s) : escalade (max_attempts)', { reason: 'verify_tx toujours KO après 1 tentative(s) : escalade (max_attempts)', attempts: 1 }, 'data_corruption', ENGINE_ESCALATED_ID)],
]

/** Réponses Prometheus `GET /api/v1/query` (vecteur instantané). */
export const PROM_SCORE = {
  status: 'success',
  data: {
    resultType: 'vector',
    result: [
      { metric: { __name__: 'resilience_anomaly_score', service: 'payment-api', job: 'detector' }, value: [1761037200, '0.83'] },
      { metric: { __name__: 'resilience_anomaly_score', service: 'auth', job: 'detector' }, value: [1761037200, '0.12'] },
    ],
  },
}
export const PROM_UP = {
  status: 'success',
  data: {
    resultType: 'vector',
    result: [
      { metric: { __name__: 'up', job: 'payment-api', instance: 'payment-api:8001' }, value: [1761037200, '0'] },
      { metric: { __name__: 'up', job: 'auth', instance: 'auth:8002' }, value: [1761037200, '1'] },
      { metric: { __name__: 'up', job: 'waf-exporter', instance: 'waf:9188' }, value: [1761037200, '1'] },
      { metric: { __name__: 'up', job: 'cadvisor', instance: 'cadvisor:8080' }, value: [1761037200, '1'] },
    ],
  },
}
