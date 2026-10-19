import { describe, expect, it } from 'vitest'
import { parseAmount, validateTransfer } from './validation'

const base = { fromAccount: '1', toAccount: '2', amount: '10', balance: 100 }

describe('validateTransfer', () => {
  it('accepte un virement valide (virgule décimale, espaces de milliers)', () => {
    expect(validateTransfer({ ...base, amount: '12,50' })).toEqual({})
    expect(validateTransfer({ ...base, amount: '1 000', balance: 2000 })).toEqual({})
  })
  it('refuse montant vide, nul, négatif, non numérique', () => {
    for (const amount of ['', '0', '-5', 'abc', '0,00']) {
      expect(validateTransfer({ ...base, amount }).amount).toBeTruthy()
    }
  })
  it('refuse plus de deux décimales', () => {
    expect(validateTransfer({ ...base, amount: '1.234' }).amount).toBe('Deux décimales maximum.')
  })
  it('refuse un montant supérieur au solde', () => {
    expect(validateTransfer({ ...base, amount: '100.01' }).amount).toMatch(/solde/)
  })
  it('bénéficiaire : obligatoire, id entier positif, différent du débiteur', () => {
    expect(validateTransfer({ ...base, toAccount: ' ' }).toAccount).toBe('Indiquez le compte bénéficiaire.')
    expect(validateTransfer({ ...base, toAccount: 'FR77' }).toAccount).toMatch(/entier positif/)
    expect(validateTransfer({ ...base, toAccount: '0' }).toAccount).toMatch(/entier positif/)
    expect(validateTransfer({ ...base, toAccount: '1' }).toAccount).toMatch(/différent/)
  })
})

describe('parseAmount', () => {
  it('convertit la saisie française en euros arrondis au centime', () => {
    expect(parseAmount('12,5')).toBe(12.5)
    expect(parseAmount('1 250,50')).toBe(1250.5)
    expect(parseAmount('abc')).toBeNull()
  })
})
