import {
  INCIDENT_TYPES,
  STREAM_EVENT_NAMES,
  type ActionResult,
  type AnomalyEvent,
  type FeatureContribution,
  type IncidentType,
  type PlannedAction,
  type ServiceHealth,
  type ServiceStatus,
  type StreamMessage,
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
