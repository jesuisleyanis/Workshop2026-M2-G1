import { describe, expect, it } from 'vitest'
import { healthMessage, queryUrl, scoreMessages, vectorSamples } from './prometheus'
import { PROM_SCORE, PROM_UP } from '../test/fixtures'

describe('lecture Prometheus (score ML + santé)', () => {
  it('resilience_anomaly_score{service} -> un message score par service, horodaté par Prometheus', () => {
    const msgs = scoreMessages(PROM_SCORE)
    expect(msgs).toEqual([
      { kind: 'score', ts: '2025-10-21T09:00:00.000Z', service: 'payment-api', score: 0.83, threshold: 0.6 },
      { kind: 'score', ts: '2025-10-21T09:00:00.000Z', service: 'auth', score: 0.12, threshold: 0.6 },
    ])
  })

  it('up{job} -> health : jobs mappés vers les services affichés, inconnus ignorés', () => {
    const h = healthMessage(PROM_UP)
    expect(h?.kind === 'health' && h.services).toEqual([
      { name: 'payment-api', status: 'down', detail: 'cible Prometheus injoignable' },
      { name: 'auth', status: 'up', detail: undefined },
      { name: 'waf', status: 'up', detail: undefined },
    ])
  })

  it('réponses invalides ou vides -> rien (jamais d’exception)', () => {
    for (const raw of [null, 'x', {}, { status: 'error' }, { status: 'success', data: { result: [{ metric: {}, value: ['t', 'nan'] }] } }]) {
      expect(vectorSamples(raw)).toEqual([])
      expect(scoreMessages(raw)).toEqual([])
      expect(healthMessage(raw)).toBeNull()
    }
    expect(scoreMessages({ status: 'success', data: { result: [{ metric: { service: 'x' }, value: [1, '7'] }] } })).toEqual([]) // hors [0,1]
  })

  it('URL de requête : API instantanée, requête encodée', () => {
    expect(queryUrl('/prometheus', 'up')).toBe('/prometheus/api/v1/query?query=up')
    expect(queryUrl('/prometheus', 'resilience_anomaly_score{service="auth"}')).toContain('query=resilience_anomaly_score%7Bservice%3D%22auth%22%7D')
  })
})
