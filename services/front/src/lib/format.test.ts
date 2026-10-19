import { describe, expect, it } from 'vitest'
import { amountToInput, formatDate, formatIban, formatMoney, shortIban } from './format'

describe('format', () => {
  it('formate les montants en EUR fr-FR', () => {
    expect(formatMoney(1250.5)).toMatch(/1\s?250,50\s?€/)
  })
  it('regroupe et abrège les IBAN', () => {
    expect(formatIban('FR7630001007941234567890185')).toBe('FR76 3000 1007 9412 3456 7890 185')
    expect(shortIban('FR76 3000 1007 9412')).toBe('FR76 … 9412')
    expect(shortIban('FR-1')).toBe('FR-1')
  })
  it('date absente ou illisible => tiret', () => {
    expect(formatDate('')).toBe('—')
    expect(formatDate('pas-une-date')).toBe('—')
  })
  it('montant -> valeur de champ', () => {
    expect(amountToInput(1250.5)).toBe('1250,50')
  })
})
