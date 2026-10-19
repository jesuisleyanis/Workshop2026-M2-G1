// Faux moteur de remédiation pour le dev/les répétitions du dashboard (aucune dépendance).
//   npm run mock            -> écoute :8005, GET /stream (SSE), GET /trigger?type=service_flood
//   AUTO=40 npm run mock    -> rejoue un incident toutes les 40 s
// Le flux /stream émet l'ENVELOPPE RÉELLE du moteur (`event: timeline`, remediation/timeline.py :
// phases detection/decision/action/verification/closure/escalation). Le mock sert aussi
// GET /api/v1/query (réponses Prometheus factices : resilience_anomaly_score, up) pour le polling
// score/santé du dashboard : PROMETHEUS_PROXY_TARGET=http://localhost:8005 npm run dev.
import { createServer } from 'node:http'
import { randomUUID } from 'node:crypto'

const PORT = Number(process.env.PORT ?? 8005)
const AUTO = Number(process.env.AUTO ?? 0)
const clients = new Set()
let state = { score: 0.12, down: false }

const now = () => new Date().toISOString()
const jitter = (base, amp) => Math.max(0, Math.min(1, base + (Math.random() - 0.5) * amp))

setInterval(() => clients.size && [...clients].forEach((res) => res.write(': keepalive\n\n')), 15000)

// Réponses Prometheus (GET /api/v1/query?query=...) : le moteur réel n'émet ni score ni santé.
const JOBS = { 'payment-api': 'payment-api', auth: 'auth', detector: 'detector', remediation: 'remediation', 'waf-exporter': 'waf', postgres: 'postgres' }
function prometheus(query) {
  const t = Math.floor(Date.now() / 1000)
  const result =
    query === 'up'
      ? Object.entries(JOBS).map(([job, svc]) => ({ metric: { __name__: 'up', job }, value: [t, state.down && svc === 'payment-api' ? '0' : '1'] }))
      : ['payment-api', 'auth', 'postgres'].map((service) => ({
          metric: { __name__: 'resilience_anomaly_score', service, job: 'detector' },
          value: [t, String(service === 'payment-api' ? jitter(state.score, 0.06) : jitter(0.1, 0.04))],
        }))
  return { status: 'success', data: { resultType: 'vector', result } }
}

let timelineId = 0
const timeline = (incident_id, incident_type, phase, status, message, data = {}) => {
  const rec = { id: ++timelineId, incident_id, incident_type, ts: now(), phase, status, message, data }
  const frame = `id: ${rec.id}\nevent: timeline\ndata: ${JSON.stringify(rec)}\n\n`
  for (const res of clients) res.write(frame)
}

const TYPES = {
  service_flood: [
    ['waf_block_ip', { source: 'from_event' }],
    ['restart_service', { service: 'payment-api' }],
  ],
  auth_abuse: [
    ['waf_block_ip', { source: 'from_event' }],
    ['tighten_rate_limit', { service: 'auth', factor: 0.5 }],
  ],
  data_corruption: [['restore_pg_dump', { backup: 'latest' }]],
}

let running = false
function scenario(type = 'service_flood') {
  if (running) return false
  running = true
  const actions = TYPES[type] ?? TYPES.service_flood
  const incident_id = `inc-${randomUUID().slice(0, 6)}`
  const t0 = Date.now()
  const at = (ms, fn) => setTimeout(fn, ms)

  const incident_type = TYPES[type] ? type : 'service_flood'
  const service = incident_type === 'data_corruption' ? 'postgres' : incident_type === 'auth_abuse' ? 'auth' : 'payment-api'
  const emit = (phase, status, message, data) => timeline(incident_id, incident_type, phase, status, message, data)

  state = { score: 0.9, down: true }
  // Mêmes (phase, status, data) que remediation/engine.py.
  emit('detection', 'info', `Anomalie détectée sur ${service} : ${incident_type}`, {
    event_id: randomUUID(),
    source: 'detector',
    anomaly_score: 0.87,
    threshold: 0.6,
    service,
    features_top: [
      { name: 'req_per_s', value: 420.0, z: 9.2 },
      { name: 'ratio_5xx', value: 0.34, z: 7.1 },
    ],
  })
  at(300, () => emit('decision', 'info', `Règle sélectionnée : ${actions.map(([t]) => t).join(' -> ')}`, { actions: actions.map(([t, params]) => ({ type: t, params })), verify: 'verify_tx', dry_run: false, max_attempts: 3, cooldown_seconds: 60 }))
  actions.forEach(([t, params], i) => {
    const t1 = 2000 + i * 2500
    at(t1, () => emit('action', 'running', `Action ${t} en cours`, { action: t, params, attempt: 1 }))
    at(t1 + 1200, () => emit('action', 'ok', `${t} : exécutée`, { action: t, attempt: 1, result: 'success', duration_ms: 1200, changed: true }))
    if (i < actions.length - 1) at(t1 + 1800, () => emit('verification', 'ko', `verify_tx KO après ${t} (essai 1/5)`, { attempt: 1, try: 1, rc: 1, detail: 'verify_tx: service injoignable', after: t }))
  })
  const verifyAt = 2000 + actions.length * 2500 + 1000
  at(verifyAt, () => {
    state = { score: 0.12, down: false }
    const last = actions.at(-1)[0]
    emit('verification', 'ok', `verify_tx OK après ${last} (essai 1/5)`, { attempt: 1, try: 1, rc: 0, detail: 'verify_tx: OK — transaction fictive créée', after: last })
    const mttr = Number(((Date.now() - t0) / 1000).toFixed(1))
    emit('closure', 'ok', `Incident clos — service rétabli (MTTR ${mttr}s)`, { mttd_seconds: 2.0, mttr_seconds: mttr, attempts: 1 })
    running = false
  })
  return true
}

if (AUTO > 0) setInterval(() => scenario(), AUTO * 1000)

createServer((req, res) => {
  const url = new URL(req.url ?? '/', 'http://localhost')
  if (url.pathname === '/stream') {
    res.writeHead(200, { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-cache', Connection: 'keep-alive', 'X-Accel-Buffering': 'no' })
    res.write(': connected\n\n')
    clients.add(res)
    req.on('close', () => clients.delete(res))
    return
  }
  if (url.pathname === '/api/v1/query') {
    res.writeHead(200, { 'Content-Type': 'application/json' })
    return res.end(JSON.stringify(prometheus(url.searchParams.get('query') ?? '')))
  }
  if (url.pathname === '/trigger') {
    const started = scenario(url.searchParams.get('type') ?? 'service_flood')
    res.writeHead(started ? 202 : 409, { 'Content-Type': 'application/json' })
    return res.end(JSON.stringify({ started }))
  }
  res.writeHead(404).end()
}).listen(PORT, () => console.log(`mock remediation sur :${PORT}  (GET /stream [event: timeline], GET /api/v1/query [Prometheus factice], GET /trigger?type=service_flood|auth_abuse|data_corruption)`))
