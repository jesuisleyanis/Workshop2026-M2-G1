import { describe, expect, it } from 'vitest'
import { presetRange, printPath, statementPath } from './statements'

describe('relevés (#50)', () => {
  const now = new Date('2026-03-15T23:30:00Z')

  it('raccourcis de période en jours UTC, bornes incluses', () => {
    expect(presetRange('month', now)).toEqual({ from: '2026-03-01', to: '2026-03-15' })
    expect(presetRange('last_month', now)).toEqual({ from: '2026-02-01', to: '2026-02-28' })
    expect(presetRange('three_months', now)).toEqual({ from: '2026-01-01', to: '2026-03-15' })
    expect(presetRange('last_month', new Date('2026-01-10T00:00:00Z'))).toEqual({ from: '2025-12-01', to: '2025-12-31' })
  })

  it('chemins API et page imprimable', () => {
    const q = { accountId: '3', from: '2026-03-01', to: '2026-03-15' }
    expect(statementPath(q, 'csv')).toBe('/api/v1/statements?account_id=3&from=2026-03-01&to=2026-03-15&format=csv')
    expect(printPath(q)).toBe('/statements/print?account=3&from=2026-03-01&to=2026-03-15')
  })
})
