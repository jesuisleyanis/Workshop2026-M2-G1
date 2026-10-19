import { describe, expect, it } from 'vitest'
import { buildTimeline, derivePhase, incidentMttr, initialState, latestIncident, reducer, scoreLevel, HISTORY_MAX, type Action } from './state'
import { parseStreamMessage } from './parse'
import { FULL_SEQUENCE, INCIDENT_ID } from '../test/fixtures'
import type { DashboardState } from '../types/events'

function play(seq: [string, unknown][], from: DashboardState = initialState): DashboardState {
  return seq.reduce((s, [name, data]) => {
    const r = parseStreamMessage(name, JSON.stringify(data))
    if (!r.ok) throw new Error(`${name}: ${r.error}`)
    return reducer(s, { type: 'message', message: r.value } satisfies Action)
  }, from)
}

const stepStatuses = (s: DashboardState) => buildTimeline(latestIncident(s)!).map((t) => t.status)

describe('phase AVANT / PENDANT / APRÈS (R20)', () => {
  it('AVANT : aucun incident, même avec scores et santé reçus', () => {
    const s = play([
      ['health', { services: [{ name: 'waf', status: 'up' }] }],
      ['score', { anomaly_score: 0.12, threshold: 0.6 }],
      ['verify_tx', { ok: true, tx_id: 'pre' }],
    ])
    expect(derivePhase(s)).toBe('before')
    expect(s.lastVerification?.ok).toBe(true)
  })

  it('PENDANT dès la détection, puis pendant la remédiation', () => {
    expect(derivePhase(play(FULL_SEQUENCE.slice(0, 1)))).toBe('during')
    expect(derivePhase(play(FULL_SEQUENCE.slice(0, 4)))).toBe('during')
  })

  it('APRÈS seulement quand verify_tx est OK', () => {
    expect(derivePhase(play(FULL_SEQUENCE))).toBe('after')
  })

  it('une vérification en échec ne passe PAS en APRÈS', () => {
    const s = play([
      ...FULL_SEQUENCE.slice(0, 4),
      ['remediation_verified', { incident_id: INCIDENT_ID, verify_tx: { ok: false } }],
    ])
    expect(derivePhase(s)).toBe('during')
  })

  it('remediation_failed reste PENDANT (escalade)', () => {
    const s = play([...FULL_SEQUENCE.slice(0, 3), ['remediation_failed', { incident_id: INCIDENT_ID, reason: 'verify_tx KO après 3 tentatives' }]])
    expect(derivePhase(s)).toBe('during')
  })

  it('un nouvel incident après un APRÈS repasse en PENDANT', () => {
    const resolved = play(FULL_SEQUENCE)
    const next = play([['remediation_started', { incident_id: 'inc-002', incident_type: 'auth_abuse', service: 'auth', actions: ['waf_block_ip'] }]], resolved)
    expect(derivePhase(next)).toBe('during')
    expect(latestIncident(next)?.id).toBe('inc-002')
  })

  it('reset ramène à AVANT et conserve connexion et santé', () => {
    const s = reducer(
      { ...play([['health', { services: [{ name: 'waf', status: 'up' }] }, ], ...FULL_SEQUENCE]), connection: 'open' },
      { type: 'reset' },
    )
    expect(derivePhase(s)).toBe('before')
    expect(s.connection).toBe('open')
    expect(s.services.find((x) => x.name === 'waf')?.status).toBe('up')
    expect(s.history).toEqual([])
  })
})

describe('timeline détection -> décision -> action -> vérification', () => {
  it('détection seule : décision en cours, reste en attente', () => {
    expect(stepStatuses(play(FULL_SEQUENCE.slice(0, 1)))).toEqual(['done', 'active', 'pending', 'pending'])
  })
  it('décision prise : action en cours', () => {
    expect(stepStatuses(play(FULL_SEQUENCE.slice(0, 2)))).toEqual(['done', 'done', 'active', 'pending'])
  })
  it("actions toutes exécutées : vérification en cours", () => {
    expect(stepStatuses(play(FULL_SEQUENCE.slice(0, 4)))).toEqual(['done', 'done', 'done', 'active'])
  })
  it('vérifiée : tout est terminé, avec décalages depuis la détection', () => {
    const s = play(FULL_SEQUENCE)
    expect(stepStatuses(s)).toEqual(['done', 'done', 'done', 'done'])
    const steps = buildTimeline(latestIncident(s)!)
    expect(steps.map((t) => t.offsetSeconds)).toEqual([0, 2, 5, 9])
    expect(steps[0]!.detail).toContain('score 0.87 / seuil 0.60')
    expect(steps[1]!.detail).toContain('Blocage IP (WAF)')
  })
  it("échec : l'étape de vérification porte l'échec quand des actions ont eu lieu", () => {
    const s = play([...FULL_SEQUENCE.slice(0, 3), ['remediation_failed', { incident_id: INCIDENT_ID, reason: 'KO' }]])
    expect(stepStatuses(s)).toEqual(['done', 'done', 'pending', 'failed'])
  })
  it("échec avant toute action : l'étape d'action est en échec", () => {
    const s = play([...FULL_SEQUENCE.slice(0, 2), ['remediation_failed', { incident_id: INCIDENT_ID, reason: 'socket-proxy refusé' }]])
    expect(stepStatuses(s)).toEqual(['done', 'done', 'failed', 'pending'])
  })
})

describe('MTTD / MTTR', () => {
  it('utilise les valeurs fournies par le moteur', () => {
    const i = latestIncident(play(FULL_SEQUENCE))!
    expect(i.mttdSeconds).toBe(4.2)
    expect(incidentMttr(i)).toBe(9)
  })
  it('repli MTTR : détection -> vérification quand le moteur ne le fournit pas', () => {
    const seq = FULL_SEQUENCE.map(([n, d]) => (n === 'remediation_verified' ? [n, { ...(d as object), mttr_seconds: undefined }] : [n, d])) as [string, unknown][]
    expect(incidentMttr(latestIncident(play(seq))!)).toBe(9)
  })
  it('pas de MTTR tant que non vérifié', () => {
    expect(incidentMttr(latestIncident(play(FULL_SEQUENCE.slice(0, 3)))!)).toBeNull()
  })
})

describe('score', () => {
  it('niveaux relatifs au seuil', () => {
    expect(scoreLevel(0.1, 0.6)).toBe('normal')
    expect(scoreLevel(0.5, 0.6)).toBe('warning')
    expect(scoreLevel(0.6, 0.6)).toBe('alert')
    expect(scoreLevel(0.87, 0.6)).toBe('alert')
  })
  it(`historique plafonné à ${HISTORY_MAX} points`, () => {
    const seq: [string, unknown][] = Array.from({ length: HISTORY_MAX + 20 }, (_, i) => ['score', { anomaly_score: (i % 10) / 10 }])
    const s = play(seq)
    expect(s.history).toHaveLength(HISTORY_MAX)
    expect(s.score?.threshold).toBe(0.6)
  })
  it("l'AnomalyEvent met aussi à jour le score courant", () => {
    expect(play(FULL_SEQUENCE.slice(0, 1)).score?.score).toBe(0.87)
  })
})

describe('robustesse', () => {
  it('remediation_* sur un incident jamais détecté crée un incident (flux rejoint en cours de route)', () => {
    const s = play([['remediation_action', { incident_id: 'orphan', action: 'restart_service', result: 'ok' }]])
    expect(latestIncident(s)?.id).toBe('orphan')
    expect(derivePhase(s)).toBe('during')
  })
  it('anomalie répétée sur le même incident : un seul incident, détection initiale conservée', () => {
    const again = ['anomaly_detected', { ...(FULL_SEQUENCE[0]![1] as object), ts: '2026-10-21T09:15:00.000Z' }] as [string, unknown]
    const s = play([FULL_SEQUENCE[0]!, again])
    expect(s.incidents).toHaveLength(1)
    expect(s.incidents[0]!.detectedAt).toBe('2026-10-21T09:14:35.000Z')
  })
  it('health fusionne par nom de service', () => {
    const s = play([['health', { services: [{ name: 'payment-api', status: 'down' }] }]])
    expect(s.services.find((x) => x.name === 'payment-api')?.status).toBe('down')
    expect(s.services.find((x) => x.name === 'waf')?.status).toBe('unknown')
  })
})
