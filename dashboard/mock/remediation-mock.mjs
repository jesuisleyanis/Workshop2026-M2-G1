// Faux moteur de remédiation pour le dev/les répétitions du dashboard (aucune dépendance).
//   npm run mock            -> écoute :8005, GET /stream (SSE), GET /trigger?type=service_flood
//   AUTO=40 npm run mock    -> rejoue un incident toutes les 40 s
// Les messages respectent docs/contracts.md §3 (AnomalyEvent) + l'enveloppe décrite dans le CDC.
import { createServer } from 'node:http'
import { randomUUID } from 'node:crypto'

const PORT = Number(process.env.PORT ?? 8005)
const AUTO = Number(process.env.AUTO ?? 0)
const clients = new Set()
const SERVICES = ['waf', 'front', 'auth', 'payment-api', 'postgres', 'detector']
let state = { score: 0.12, down: false }

function send(name, data) {
  const frame = `event: ${name}\ndata: ${JSON.stringify(data)}\n\n`
  for (const res of clients) res.write(frame)
}
const now = () => new Date().toISOString()
const jitter = (base, amp) => Math.max(0, Math.min(1, base + (Math.random() - 0.5) * amp))

setInterval(() => send('score', { ts: now(), service: 'payment-api', anomaly_score: jitter(state.score, 0.06), threshold: 0.6 }), 1000)
setInterval(
  () =>
    send('health', {
      ts: now(),
      services: SERVICES.map((name) => ({ name, status: state.down && name === 'payment-api' ? 'down' : 'up' })),
    }),
  3000,
)
setInterval(() => !state.down && send('verify_tx', { ts: now(), ok: true, tx_id: `verify-${randomUUID().slice(0, 8)}`, duration_ms: 60 + Math.round(Math.random() * 40) }), 10000)

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

  state = { score: 0.9, down: true }
  send('anomaly_detected', {
    schema_version: '1.0',
    event_id: randomUUID(),
    incident_id,
    ts: now(),
    source: 'detector',
    service: 'payment-api',
    anomaly_score: 0.87,
    threshold: 0.6,
    incident_type: TYPES[type] ? type : 'service_flood',
    features_top: [
      { name: 'req_per_s', value: 420.0, z: 9.2 },
      { name: 'ratio_5xx', value: 0.34, z: 7.1 },
    ],
    evidence: { prometheus_query: 'rate(resilience_http_requests_total[1m])', loki_query: '{service="payment-api"} |= "db_error"' },
  })
  at(2000, () => send('remediation_started', { ts: now(), incident_id, incident_type: type, service: 'payment-api', dry_run: false, actions: actions.map(([t, params]) => ({ type: t, params })) }))
  actions.forEach(([t], i) => at(3500 + i * 2500, () => send('remediation_action', { ts: now(), incident_id, action: t, result: 'ok', attempt: 1 })))
  const verifyAt = 3500 + actions.length * 2500 + 2000
  at(verifyAt, () => {
    state = { score: 0.12, down: false }
    const mttr = (Date.now() - t0) / 1000
    send('remediation_verified', { ts: now(), incident_id, mttd_seconds: 4.2, mttr_seconds: Number(mttr.toFixed(1)), verify_tx: { ok: true, tx_id: `verify-${randomUUID().slice(0, 8)}`, ts: now(), duration_ms: 84 } })
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
  if (url.pathname === '/trigger') {
    const started = scenario(url.searchParams.get('type') ?? 'service_flood')
    res.writeHead(started ? 202 : 409, { 'Content-Type': 'application/json' })
    return res.end(JSON.stringify({ started }))
  }
  res.writeHead(404).end()
}).listen(PORT, () => console.log(`mock remediation sur :${PORT}  (GET /stream, GET /trigger?type=service_flood|auth_abuse|data_corruption)`))
