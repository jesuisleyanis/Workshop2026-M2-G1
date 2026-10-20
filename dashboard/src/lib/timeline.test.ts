/** Enveloppe RÉELLE du moteur (`event: timeline`, remediation/timeline.py) -> état du dashboard. */
import { describe, expect, it } from 'vitest'
import { adaptTimelineFrame, parseStreamMessage, parseTimelineFrame } from './parse'
import { buildTimeline, derivePhase, initialState, latestIncident, reducer, type Action } from './state'
import { ENGINE_ESCALATED_ID, ENGINE_INCIDENT_ID, ENGINE_TIMELINE, ENGINE_TIMELINE_ESCALATED } from '../test/fixtures'
import type { DashboardState, StreamMessage } from '../types/events'

const parseAll = (seq: [string, unknown][]) => seq.map(([name, data]) => parseStreamMessage(name, JSON.stringify(data)))

function play(seq: [string, unknown][], from: DashboardState = initialState): DashboardState {
  return parseAll(seq).reduce((s, r) => {
    if (!r.ok) throw new Error(r.error)
    return reducer(s, { type: 'message', message: r.value } satisfies Action)
  }, from)
}

describe('parseStreamMessage - event: timeline (enveloppe réelle du moteur)', () => {
  it('aucune trame réelle n’est rejetée : chaque (phase, status) a une traduction', () => {
    const results = parseAll([...ENGINE_TIMELINE, ...ENGINE_TIMELINE_ESCALATED])
    expect(results.every((r) => r.ok)).toBe(true)
  })

  it('traduit le déroulé service_flood vers les kinds internes attendus', () => {
    const kinds = parseAll(ENGINE_TIMELINE).map((r) => (r.ok ? r.value.kind : r.error))
    expect(kinds).toEqual([
      'anomaly_detected',
      'remediation_started',
      'timeline_note', // action running
      'remediation_action',
      'remediation_verified', // verify KO (sans MTTR)
      'timeline_note',
      'remediation_action',
      'remediation_verified', // verify OK
      'remediation_verified', // closure : MTTD / MTTR
    ])
  })

  it('reconstruit un AnomalyEvent conforme au contrat §3 depuis la trame detection', () => {
    const r = parseStreamMessage('timeline', JSON.stringify(ENGINE_TIMELINE[0]![1]))
    expect(r.ok && r.value.kind === 'anomaly_detected' && r.value).toMatchObject({
      incidentId: ENGINE_INCIDENT_ID,
      event: { schema_version: '1.0', source: 'detector', service: 'payment-api', anomaly_score: 0.87, threshold: 0.6, incident_type: 'service_flood', features_top: [{ name: 'req_per_s', value: 420, z: 9.2 }], evidence: {} },
    })
  })

  it('décision : actions planifiées et dry_run lus dans data', () => {
    const r = parseStreamMessage('timeline', JSON.stringify(ENGINE_TIMELINE[1]![1]))
    expect(r.ok && r.value).toMatchObject({ kind: 'remediation_started', incidentType: 'service_flood', service: null, dryRun: false, actions: [{ type: 'waf_block_ip' }, { type: 'restart_service' }] })
  })

  it('action : ok / failed / dry_run -> ok / failed / skipped, message = détail', () => {
    const ok = parseStreamMessage('timeline', JSON.stringify(ENGINE_TIMELINE[3]![1]))
    expect(ok.ok && ok.value).toMatchObject({ kind: 'remediation_action', action: 'waf_block_ip', result: 'ok', attempt: 1, detail: expect.stringContaining('203.0.113.7') })
    const failed = parseStreamMessage('timeline', JSON.stringify(ENGINE_TIMELINE_ESCALATED[3]![1]))
    expect(failed.ok && failed.value).toMatchObject({ kind: 'remediation_action', action: 'restore_pg_dump', result: 'failed' })
    const dry = { ...(ENGINE_TIMELINE[3]![1] as object), status: 'dry_run' }
    const skipped = parseStreamMessage('timeline', JSON.stringify(dry))
    expect(skipped.ok && skipped.value).toMatchObject({ kind: 'remediation_action', result: 'skipped' })
  })

  it('clôture : MTTD / MTTR fournis par le moteur ; escalade : raison', () => {
    const closure = parseStreamMessage('timeline', JSON.stringify(ENGINE_TIMELINE.at(-1)![1]))
    expect(closure.ok && closure.value).toMatchObject({ kind: 'remediation_verified', mttdSeconds: 4.2, mttrSeconds: 9.0, verify: { ok: true } })
    const esc = parseStreamMessage('timeline', JSON.stringify(ENGINE_TIMELINE_ESCALATED.at(-1)![1]))
    expect(esc.ok && esc.value).toMatchObject({ kind: 'remediation_failed', incidentId: ENGINE_ESCALATED_ID, reason: expect.stringContaining('max_attempts') })
  })

  it('trames sans effet (cooldown, doublon, dry-run clos) -> timeline_note, jamais un rejet', () => {
    const base = ENGINE_TIMELINE[1]![1] as Record<string, unknown>
    for (const f of [
      { ...base, status: 'skipped', data: { event_id: 'x', cooldown_remaining_s: 42 } },
      { ...base, status: 'info', data: { attempt: 2 } },
      { ...base, phase: 'detection', status: 'skipped', data: {} },
      { ...base, phase: 'closure', status: 'dry_run', data: {} },
    ]) {
      const r = parseStreamMessage('timeline', JSON.stringify(f))
      expect(r.ok && r.value.kind).toBe('timeline_note')
    }
  })

  it('trame invalide (phase / incident_type / ts inconnus) -> rejet compté (D9)', () => {
    const base = ENGINE_TIMELINE[0]![1] as Record<string, unknown>
    expect(parseTimelineFrame({ ...base, phase: 'teleport' }).ok).toBe(false)
    expect(parseTimelineFrame({ ...base, incident_type: 'bogus' }).ok).toBe(false)
    expect(parseTimelineFrame({ ...base, ts: 'hier' }).ok).toBe(false)
    expect(parseStreamMessage('timeline', JSON.stringify({ ...base, data: { service: 'payment-api' } })).ok).toBe(false) // detection sans score
    expect(parseStreamMessage('timeline', '{pas json').ok).toBe(false)
  })

  it('sans `event:` (message), une trame portant phase + incident_id est reconnue', () => {
    const r = parseStreamMessage('message', JSON.stringify(ENGINE_TIMELINE[0]![1]))
    expect(r.ok && r.value.kind).toBe('anomaly_detected')
  })

  it('adaptTimelineFrame est total sur (phase, status)', () => {
    const base = ENGINE_TIMELINE[0]![1] as Record<string, unknown>
    for (const phase of ['detection', 'decision', 'action', 'verification', 'closure', 'escalation'] as const)
      for (const status of ['info', 'running', 'ok', 'ko', 'failed', 'skipped', 'dry_run'] as const) {
        const f = parseTimelineFrame({ ...base, phase, status, data: { action: 'x', event_id: 'e', service: 's', anomaly_score: 0.5, threshold: 0.6 } })
        expect(f.ok).toBe(true)
        if (f.ok) expect(adaptTimelineFrame(f.value).ok).toBe(true)
      }
  })
})

describe('état du dashboard alimenté par l’enveloppe réelle', () => {
  it('service_flood clos : PENDANT pendant la boucle, APRÈS à la clôture, MTTD/MTTR du moteur', () => {
    expect(derivePhase(play(ENGINE_TIMELINE.slice(0, 1)))).toBe('during')
    const midway = play(ENGINE_TIMELINE.slice(0, 5)) // verify KO après waf_block_ip
    expect(derivePhase(midway)).toBe('during')
    expect(buildTimeline(latestIncident(midway)!).find((s) => s.id === 'verification')?.status).toBe('failed')

    const done = play(ENGINE_TIMELINE)
    expect(derivePhase(done)).toBe('after')
    const inc = latestIncident(done)!
    expect(inc.id).toBe(ENGINE_INCIDENT_ID)
    expect(inc.service).toBe('payment-api')
    expect(inc.actions.map((a) => [a.type, a.result])).toEqual([
      ['waf_block_ip', 'ok'],
      ['restart_service', 'ok'],
    ])
    expect(inc.mttdSeconds).toBe(4.2)
    expect(inc.mttrSeconds).toBe(9.0)
    expect(buildTimeline(inc).map((s) => s.status)).toEqual(['done', 'done', 'done', 'done'])
    expect(done.rejected).toBe(0)
    expect(done.history.at(-1)).toMatchObject({ service: 'payment-api', score: 0.87 })
  })

  it('data_corruption escaladé : reste PENDANT, échec porté par l’étape action', () => {
    const s = play(ENGINE_TIMELINE_ESCALATED)
    expect(derivePhase(s)).toBe('during')
    const inc = latestIncident(s)!
    expect(inc.incidentType).toBe('data_corruption')
    expect(inc.failure?.reason).toContain('max_attempts')
    expect(inc.actions.map((a) => a.result)).toEqual(['failed', 'ok'])
    expect(buildTimeline(inc).find((st) => st.id === 'verification')?.status).toBe('failed')
  })

  it('un incident réel après un APRÈS repasse en PENDANT ; les notes n’altèrent pas l’état', () => {
    const after = play(ENGINE_TIMELINE)
    const next = play(ENGINE_TIMELINE_ESCALATED.slice(0, 3), after)
    expect(derivePhase(next)).toBe('during')
    expect(next.incidents.map((i) => i.id)).toEqual([ENGINE_INCIDENT_ID, ENGINE_ESCALATED_ID])
    const note: StreamMessage = { kind: 'timeline_note', ts: 'x', incidentId: ENGINE_ESCALATED_ID, phase: 'action', status: 'running', message: 'm' }
    expect(reducer(next, { type: 'message', message: note })).toBe(next)
  })
})
