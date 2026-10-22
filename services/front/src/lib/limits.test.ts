import { describe, expect, it } from 'vitest'
import { exceedsLimit, remainingShare, resetLabel } from './limits'

const L = { accountId: '1', limit: 2000, used: 920, remaining: 1080, periodEnd: '2026-11-01' }

describe('plafonds (#46)', () => {
  it('part restante bornée, null sans plafond', () => {
    expect(remainingShare(L)).toBe(0.54)
    expect(remainingShare({ ...L, remaining: -5 })).toBe(0)
    expect(remainingShare({ ...L, limit: null, remaining: null })).toBeNull()
  })

  it('avertissement seulement si un plafond restant connu est dépassé', () => {
    expect(exceedsLimit(L, 1080)).toBe(false)
    expect(exceedsLimit(L, 1080.01)).toBe(true)
    expect(exceedsLimit({ ...L, limit: null, remaining: null }, 1e9)).toBe(false)
    expect(exceedsLimit(undefined, 1e9)).toBe(false)
  })

  it('date de remise à zéro sans glissement de fuseau', () => {
    expect(resetLabel('2026-11-01')).toBe('1 novembre')
    expect(resetLabel('nope')).toBe('—')
  })
})
