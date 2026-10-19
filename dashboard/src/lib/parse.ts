import {
  INCIDENT_TYPES,
  STREAM_EVENT_NAMES,
  TIMELINE_EVENT_NAME,
  TIMELINE_PHASES,
  TIMELINE_STATUSES,
  type ActionResult,
  type AnomalyEvent,
  type FeatureContribution,
  type IncidentType,
  type PlannedAction,
  type ServiceHealth,
  type ServiceStatus,
  type StreamMessage,
  type TimelineFrame,
  type TimelinePhase,
  type TimelineStatus,
  type VerifyTx,
} from '../types/events'

export type Result<T> = { ok: true; value: T } | { ok: false; error: string }

const ok = <T>(value: T): Result<T> => ({ ok: true, value })
const fail = <T = never>(error: string): Result<T> => ({ ok: false, error })

type Obj = Record<string, unknown>
const isObj = (v: unknown): v is Obj => typeof v === 'object' && v !== null && !Array.isArray(v)
const isStr = (v: unknown): v is string => typeof v === 'string' && v !== ''
const isNum = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v)
const isIso = (v: unknown): v is string => isStr(v) && !Number.isNaN(Date.parse(v))
const isIncidentType = (v: unknown): v is IncidentType => (INCIDENT_TYPES as readonly unknown[]).includes(v)

function parseFeature(v: unknown, i: number): Result<FeatureContribution> {
  if (!isObj(v)) return fail(`features_top[${i}] n'est pas un objet`)
  if (!isStr(v.name)) return fail(`features_top[${i}].name manquant`)
  if (!isNum(v.value)) return fail(`features_top[${i}].value invalide`)
  if (!isNum(v.z)) return fail(`features_top[${i}].z invalide`)
  return ok({ name: v.name, value: v.value, z: v.z })
}

/** Valide un objet contre le schéma d'événement d'anomalie (docs/contracts.md §3). */
export function parseAnomalyEvent(raw: unknown): Result<AnomalyEvent> {
  if (!isObj(raw)) return fail("l'événement n'est pas un objet JSON")
  if (!isStr(raw.schema_version)) return fail('schema_version manquant')
  if (!/^1(\.|$)/.test(raw.schema_version)) return fail(`schema_version non supportée : ${raw.schema_version}`)
  if (!isStr(raw.event_id)) return fail('event_id manquant')
  if (!isIso(raw.ts)) return fail('ts invalide (ISO 8601 attendu)')
  if (!isStr(raw.source)) return fail('source manquante')
  if (!isStr(raw.service)) return fail('service manquant')
  if (!isNum(raw.anomaly_score) || raw.anomaly_score < 0) return fail('anomaly_score invalide')
  if (!isNum(raw.threshold) || raw.threshold < 0) return fail('threshold invalide')
  if (!isIncidentType(raw.incident_type)) return fail(`incident_type inconnu : ${String(raw.incident_type)}`)
  if (!Array.isArray(raw.features_top)) return fail('features_top doit être un tableau')

  const features: FeatureContribution[] = []
  for (const [i, f] of raw.features_top.entries()) {
    const r = parseFeature(f, i)
    if (!r.ok) return fail(r.error)
    features.push(r.value)
  }

  const ev = isObj(raw.evidence) ? raw.evidence : {}
  const evidence: AnomalyEvent['evidence'] = {}
  if (isStr(ev.prometheus_query)) evidence.prometheus_query = ev.prometheus_query
  if (isStr(ev.loki_query)) evidence.loki_query = ev.loki_query

  return ok({
    schema_version: raw.schema_version,
    event_id: raw.event_id,
    ts: raw.ts,
    source: raw.source,
    service: raw.service,
    anomaly_score: raw.anomaly_score,
    threshold: raw.threshold,
    incident_type: raw.incident_type,
    features_top: features,
    evidence,
  })
}

const STATUSES: ServiceStatus[] = ['up', 'degraded', 'down', 'unknown']

function parseVerify(v: unknown, fallbackTs: string): Result<VerifyTx> {
  if (!isObj(v) || typeof v.ok !== 'boolean') return fail('verify_tx.ok manquant')
  return ok({
    ok: v.ok,
    ts: isIso(v.ts) ? v.ts : fallbackTs,
    txId: isStr(v.tx_id) ? v.tx_id : null,
    durationMs: isNum(v.duration_ms) ? v.duration_ms : null,
  })
}

function parsePlannedActions(v: unknown): PlannedAction[] {
  if (!Array.isArray(v)) return []
  const out: PlannedAction[] = []
  for (const a of v) {
    if (typeof a === 'string' && a) out.push({ type: a })
    else if (isObj(a) && isStr(a.type)) out.push({ type: a.type, params: isObj(a.params) ? a.params : undefined })
  }
  return out
}

const isPhase = (v: unknown): v is TimelinePhase => (TIMELINE_PHASES as readonly unknown[]).includes(v)
const isStatus = (v: unknown): v is TimelineStatus => (TIMELINE_STATUSES as readonly unknown[]).includes(v)

/** Valide l'enveloppe réelle du moteur (`event: timeline`, remediation/timeline.py). */
export function parseTimelineFrame(raw: unknown): Result<TimelineFrame> {
  if (!isObj(raw)) return fail('timeline : trame non objet')
  if (!isStr(raw.incident_id)) return fail('timeline : incident_id manquant')
  if (!isIncidentType(raw.incident_type)) return fail(`timeline : incident_type inconnu : ${String(raw.incident_type)}`)
  if (!isIso(raw.ts)) return fail('timeline : ts invalide')
  if (!isPhase(raw.phase)) return fail(`timeline : phase inconnue : ${String(raw.phase)}`)
  if (!isStatus(raw.status)) return fail(`timeline : status inconnu : ${String(raw.status)}`)
  return ok({
    id: isNum(raw.id) ? raw.id : 0,
    incident_id: raw.incident_id,
    incident_type: raw.incident_type,
    ts: raw.ts,
    phase: raw.phase,
    status: raw.status,
    message: isStr(raw.message) ? raw.message : '',
    data: isObj(raw.data) ? raw.data : {},
  })
}

/**
 * Adaptateur enveloppe moteur -> messages internes. Table (phase, status) -> kind :
 *   detection/info        -> anomaly_detected (AnomalyEvent reconstruit depuis data, validé §3)
 *   decision/info+actions -> remediation_started
 *   action/ok|failed|dry_run -> remediation_action (dry_run => "skipped")
 *   verification/ok|ko    -> remediation_verified (verify_tx.ok ; sans MTTR)
 *   closure/ok            -> remediation_verified (+ mttd_seconds, mttr_seconds)
 *   escalation/failed     -> remediation_failed
 *   tout le reste (running, skipped, cooldown, dry_run clos) -> timeline_note (accepté, sans effet)
 */
export function adaptTimelineFrame(f: TimelineFrame): Result<StreamMessage> {
  const d = f.data
  const base = { ts: f.ts, incidentId: f.incident_id }
  const note = (): Result<StreamMessage> => ok({ kind: 'timeline_note', ...base, phase: f.phase, status: f.status, message: f.message })

  switch (f.phase) {
    case 'detection': {
      if (f.status !== 'info') return note()
      const ev = parseAnomalyEvent({
        schema_version: '1.0',
        event_id: d.event_id,
        ts: f.ts,
        source: d.source ?? 'detector',
        service: d.service,
        anomaly_score: d.anomaly_score,
        threshold: d.threshold,
        incident_type: f.incident_type,
        features_top: d.features_top ?? [],
        evidence: d.evidence,
      })
      if (!ev.ok) return fail(`timeline/detection : ${ev.error}`)
      return ok({ kind: 'anomaly_detected', incidentId: f.incident_id, event: ev.value })
    }
    case 'decision':
      if (f.status !== 'info' || !Array.isArray(d.actions)) return note()
      return ok({
        kind: 'remediation_started',
        ...base,
        incidentType: f.incident_type,
        service: isStr(d.service) ? d.service : null,
        actions: parsePlannedActions(d.actions),
        dryRun: d.dry_run === true,
      })
    case 'action': {
      if (f.status === 'running') return note()
      if (!isStr(d.action)) return fail('timeline/action : data.action manquant')
      const result: ActionResult = f.status === 'failed' ? 'failed' : f.status === 'dry_run' ? 'skipped' : 'ok'
      return ok({ kind: 'remediation_action', ...base, action: d.action, result, detail: f.message || null, attempt: isNum(d.attempt) ? d.attempt : null })
    }
    case 'verification':
      if (f.status !== 'ok' && f.status !== 'ko') return note()
      return ok({
        kind: 'remediation_verified',
        ...base,
        verify: { ok: f.status === 'ok', ts: f.ts, txId: null, durationMs: null },
        mttdSeconds: null,
        mttrSeconds: null,
      })
    case 'closure':
      if (f.status !== 'ok') return note()
      return ok({
        kind: 'remediation_verified',
        ...base,
        verify: { ok: true, ts: f.ts, txId: null, durationMs: null },
        mttdSeconds: isNum(d.mttd_seconds) ? d.mttd_seconds : null,
        mttrSeconds: isNum(d.mttr_seconds) ? d.mttr_seconds : null,
      })
    case 'escalation':
      return ok({ kind: 'remediation_failed', ...base, reason: isStr(d.reason) ? d.reason : f.message || 'escalade' })
  }
}

/** Valide et normalise un message du flux SSE de remédiation. */
export function parseStreamMessage(eventName: string, data: string): Result<StreamMessage> {
  let json: unknown
  try {
    json = JSON.parse(data)
  } catch {
    return fail('JSON invalide')
  }
  if (!isObj(json)) return fail('message non objet')

  // Événement SSE sans `event:` => le type est porté par le corps (`type` ou `event`).
  const kind = eventName && eventName !== 'message' ? eventName : String(json.type ?? json.event ?? '')
  if (kind === TIMELINE_EVENT_NAME || (kind === '' && isStr(json.phase) && isStr(json.incident_id))) {
    const frame = parseTimelineFrame(json)
    return frame.ok ? adaptTimelineFrame(frame.value) : fail(frame.error)
  }
  if (!(STREAM_EVENT_NAMES as string[]).includes(kind)) return fail(`type de message inconnu : ${kind || '(vide)'}`)

  const ts = isIso(json.ts) ? json.ts : new Date().toISOString()

  switch (kind) {
    case 'health': {
      if (!Array.isArray(json.services)) return fail('health.services manquant')
      const services: ServiceHealth[] = []
      for (const s of json.services) {
        if (!isObj(s) || !isStr(s.name)) return fail('health.services[].name manquant')
        const status = STATUSES.includes(s.status as ServiceStatus) ? (s.status as ServiceStatus) : 'unknown'
        services.push({ name: s.name, status, detail: isStr(s.detail) ? s.detail : undefined })
      }
      return ok({ kind: 'health', ts, services })
    }
    case 'score': {
      if (!isNum(json.anomaly_score)) return fail('score.anomaly_score invalide')
      return ok({
        kind: 'score',
        ts,
        service: isStr(json.service) ? json.service : 'payment-api',
        score: json.anomaly_score,
        threshold: isNum(json.threshold) ? json.threshold : 0.6,
      })
    }
    case 'anomaly_detected': {
      const ev = parseAnomalyEvent(json)
      if (!ev.ok) return fail(ev.error)
      return ok({
        kind: 'anomaly_detected',
        incidentId: isStr(json.incident_id) ? json.incident_id : ev.value.event_id,
        event: ev.value,
      })
    }
    case 'remediation_started': {
      if (!isStr(json.incident_id)) return fail('incident_id manquant')
      return ok({
        kind: 'remediation_started',
        ts,
        incidentId: json.incident_id,
        incidentType: isIncidentType(json.incident_type) ? json.incident_type : null,
        service: isStr(json.service) ? json.service : null,
        actions: parsePlannedActions(json.actions),
        dryRun: json.dry_run === true,
      })
    }
    case 'remediation_action': {
      if (!isStr(json.incident_id)) return fail('incident_id manquant')
      const a = json.action
      const action = isStr(a) ? a : isObj(a) && isStr(a.type) ? a.type : ''
      if (!action) return fail('action manquante')
      const result: ActionResult = json.result === 'failed' || json.result === 'skipped' ? json.result : 'ok'
      return ok({
        kind: 'remediation_action',
        ts,
        incidentId: json.incident_id,
        action,
        result,
        detail: isStr(json.detail) ? json.detail : null,
        attempt: isNum(json.attempt) ? json.attempt : null,
      })
    }
    case 'remediation_verified': {
      if (!isStr(json.incident_id)) return fail('incident_id manquant')
      const verify = parseVerify(json.verify_tx ?? { ok: true }, ts)
      if (!verify.ok) return fail(verify.error)
      return ok({
        kind: 'remediation_verified',
        ts,
        incidentId: json.incident_id,
        verify: verify.value,
        mttdSeconds: isNum(json.mttd_seconds) ? json.mttd_seconds : null,
        mttrSeconds: isNum(json.mttr_seconds) ? json.mttr_seconds : null,
      })
    }
    case 'remediation_failed': {
      if (!isStr(json.incident_id)) return fail('incident_id manquant')
      return ok({
        kind: 'remediation_failed',
        ts,
        incidentId: json.incident_id,
        reason: isStr(json.reason) ? json.reason : 'échec non détaillé',
      })
    }
    case 'verify_tx': {
      const verify = parseVerify(json, ts)
      if (!verify.ok) return fail(verify.error)
      return ok({ kind: 'verify_tx', verify: verify.value })
    }
    default:
      return fail(`type de message inconnu : ${kind}`)
  }
}
