import { describe, expect, it } from 'vitest'
import { parseAmount, validateTransfer } from './validation'

const base = { fromAccount: 'A', toAccount: 'B', amount: '10', balance: 100 }

describe('validateTransfer', () => {
  it('accepte un virement valide (virgule décimale)', () => {
    expect(validateTransfer({ ...base, amount: '12,50' })).toEqual({})
  })
  it('refuse montant nul, négatif, non numérique ou > 2 décimales', () => {
    for (const amount of ['', '0', '-5', 'abc', '1.234']) {
      expect(validateTransfer({ ...base, amount }).amount).toBeTruthy()
    }
  })
  it('refuse un montant supérieur au solde', () => {
    expect(validateTransfer({ ...base, amount: '100.01' }).amount).toMatch(/solde/)
  })
  it('refuse bénéficiaire vide ou identique au débiteur', () => {
    expect(validateTransfer({ ...base, toAccount: ' ' }).toAccount).toBeTruthy()
    expect(validateTransfer({ ...base, toAccount: 'A' }).toAccount).toBeTruthy()
  })
  it('parseAmount arrondit au centime', () => {
    expect(parseAmount('12,5')).toBe(12.5)
  })
})
