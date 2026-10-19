import { describe, expect, it } from 'vitest'
import { parseAnomalyEvent, parseStreamMessage } from './parse'
import { CONTRACT_ANOMALY_EVENT, INCIDENT_ID } from '../test/fixtures'
import { INCIDENT_TYPES } from '../types/events'

describe('parseAnomalyEvent - schéma docs/contracts.md §3', () => {
  it("accepte l'exemple du contrat tel quel", () => {
    const r = parseAnomalyEvent(CONTRACT_ANOMALY_EVENT)
    expect(r.ok).toBe(true)
    if (!r.ok) return
    expect(r.value).toMatchObject({
      schema_version: '1.0',
      source: 'detector',
      service: 'payment-api',
      anomaly_score: 0.87,
      threshold: 0.6,
      incident_type: 'service_flood',
    })
    expect(r.value.features_top).toEqual([
      { name: 'req_per_s', value: 420, z: 9.2 },
      { name: 'ratio_5xx', value: 0.34, z: 7.1 },
    ])
    expect(r.value.evidence.prometheus_query).toContain('resilience_http_requests_total')
    expect(r.value.evidence.loki_query).toContain('db_error')
  })

  it.each(INCIDENT_TYPES)('accepte incident_type=%s (énumération figée)', (incident_type) => {
    expect(parseAnomalyEvent({ ...CONTRACT_ANOMALY_EVENT, incident_type }).ok).toBe(true)
  })

  it('accepte une alerte Alertmanager au même format (source différente)', () => {
    expect(parseAnomalyEvent({ ...CONTRACT_ANOMALY_EVENT, source: 'alertmanager' }).ok).toBe(true)
  })

  it('évidence absente => objet vide', () => {
    const { evidence: _evidence, ...rest } = CONTRACT_ANOMALY_EVENT
    void _evidence
    const r = parseAnomalyEvent(rest)
    expect(r.ok && r.value.evidence).toEqual({})
  })

  it.each([
    ['incident_type hors énumération', { incident_type: 'ransomware' }, /incident_type/],
    ['schema_version majeure inconnue', { schema_version: '2.0' }, /schema_version/],
    ['anomaly_score absent', { anomaly_score: undefined }, /anomaly_score/],
    ['anomaly_score non numérique', { anomaly_score: '0.9' }, /anomaly_score/],
    ['threshold absent', { threshold: undefined }, /threshold/],
    ['ts non ISO', { ts: 'hier' }, /ts/],
    ['event_id vide', { event_id: '' }, /event_id/],
    ['service absent', { service: undefined }, /service/],
    ['features_top non tableau', { features_top: 'x' }, /features_top/],
    ['feature sans z', { features_top: [{ name: 'a', value: 1 }] }, /\.z/],
  ])('rejette : %s', (_label, patch, message) => {
    const r = parseAnomalyEvent({ ...CONTRACT_ANOMALY_EVENT, ...patch })
    expect(r.ok).toBe(false)
    if (!r.ok) expect(r.error).toMatch(message)
  })

  it('rejette un non-objet', () => {
    expect(parseAnomalyEvent(null).ok).toBe(false)
    expect(parseAnomalyEvent([]).ok).toBe(false)
  })
})

describe('parseStreamMessage', () => {
  it("anomaly_detected : conserve l'AnomalyEvent et l'incident_id", () => {
    const r = parseStreamMessage('anomaly_detected', JSON.stringify({ ...CONTRACT_ANOMALY_EVENT, incident_id: INCIDENT_ID }))
    expect(r.ok && r.value.kind === 'anomaly_detected' && r.value.incidentId).toBe(INCIDENT_ID)
  })

  it("anomaly_detected sans incident_id : repli sur event_id", () => {
    const r = parseStreamMessage('anomaly_detected', JSON.stringify(CONTRACT_ANOMALY_EVENT))
    expect(r.ok && r.value.kind === 'anomaly_detected' && r.value.incidentId).toBe(CONTRACT_ANOMALY_EVENT.event_id)
  })

  it('anomaly_detected non conforme => rejeté', () => {
    const r = parseStreamMessage('anomaly_detected', JSON.stringify({ ...CONTRACT_ANOMALY_EVENT, incident_type: 'nope' }))
    expect(r.ok).toBe(false)
  })

  it('événement SSE par défaut ("message") : le type vient du corps', () => {
    const r = parseStreamMessage('message', JSON.stringify({ type: 'score', anomaly_score: 0.2, threshold: 0.6 }))
    expect(r.ok && r.value).toMatchObject({ kind: 'score', score: 0.2 })
  })

  it('health : statuts inconnus ramenés à unknown', () => {
    const r = parseStreamMessage('health', JSON.stringify({ services: [{ name: 'waf', status: 'up' }, { name: 'auth', status: 'weird' }] }))
    expect(r.ok && r.value.kind === 'health' && r.value.services.map((s) => s.status)).toEqual(['up', 'unknown'])
  })

  it('remediation_verified : verify_tx + MTTD/MTTR', () => {
    const r = parseStreamMessage(
      'remediation_verified',
      JSON.stringify({ incident_id: 'i', mttd_seconds: 4, mttr_seconds: 12.5, verify_tx: { ok: true, tx_id: 'x', duration_ms: 50 } }),
    )
    expect(r.ok && r.value).toMatchObject({ kind: 'remediation_verified', mttdSeconds: 4, mttrSeconds: 12.5, verify: { ok: true, txId: 'x', durationMs: 50 } })
  })

  it('remediation_action : action en chaîne ou objet, résultat par défaut ok', () => {
    const a = parseStreamMessage('remediation_action', JSON.stringify({ incident_id: 'i', action: 'restart_service' }))
    const b = parseStreamMessage('remediation_action', JSON.stringify({ incident_id: 'i', action: { type: 'waf_block_ip' }, result: 'failed' }))
    expect(a.ok && a.value).toMatchObject({ action: 'restart_service', result: 'ok' })
    expect(b.ok && b.value).toMatchObject({ action: 'waf_block_ip', result: 'failed' })
  })

  it('rejette JSON invalide, type inconnu, incident_id manquant', () => {
    expect(parseStreamMessage('health', '{pas json').ok).toBe(false)
    expect(parseStreamMessage('inconnu', '{}').ok).toBe(false)
    expect(parseStreamMessage('remediation_failed', JSON.stringify({ reason: 'x' })).ok).toBe(false)
    expect(parseStreamMessage('message', '{}').ok).toBe(false)
  })
})
