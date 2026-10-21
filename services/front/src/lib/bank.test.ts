import { describe, expect, it } from 'vitest'
import { csvCell, groupByDay, historyCsv, recipients, spendingPeriod, txView } from './bank'
import type { Account, Transaction } from '../types/api'

const tx = (id: string, from: string, to: string, amount: number, createdAt: string, status: Transaction['status'] = 'created'): Transaction => ({
  id,
  fromAccount: from,
  toAccount: to,
  amount,
  currency: 'EUR',
  status,
  label: null,
  createdAt,
  requestId: null,
})
const acc = (id: string): Account => ({ id, owner: null, label: null, iban: `FR76 0000 000${id}`, balance: 100, currency: 'EUR' })
const mine = new Set(['1', '2'])

describe('bank — vues client', () => {
  it('sens, montant signé et contrepartie', () => {
    expect(txView(tx('a', '1', '9', 20, ''), mine)).toMatchObject({ direction: 'out', delta: -20, counterpart: 'Compte n°9', title: 'Virement émis' })
    expect(txView(tx('b', '9', '1', 5, ''), mine)).toMatchObject({ direction: 'in', delta: 5, title: 'Virement reçu' })
    expect(txView(tx('c', '1', '2', 5, ''), mine)).toMatchObject({ direction: 'internal', delta: 0, title: 'Virement interne' })
    expect(txView(tx('d', '1', '9', 5, ''), mine, 'Loyer').title).toBe('Loyer')
  })

  it('regroupe par jour et exclut les rejets de la somme', () => {
    const now = new Date('2026-10-21T12:00:00')
    const views = [
      txView(tx('1', '1', '9', 20, '2026-10-21T10:00:00'), mine),
      txView(tx('2', '1', '9', 999, '2026-10-21T09:00:00', 'rejected'), mine),
      txView(tx('3', '9', '1', 5, '2026-10-20T09:00:00'), mine),
    ]
    const g = groupByDay(views, now)
    expect(g.map((x) => [x.label, x.sum, x.items.length])).toEqual([
      ["Aujourd'hui", -20, 2],
      ['Hier', 5, 1],
    ])
  })

  it('dépenses de la semaine : débits effectués vers l’extérieur seulement, jours futurs marqués', () => {
    const now = new Date('2026-10-21T12:00:00') // mercredi
    const views = [
      txView(tx('1', '1', '9', 20, '2026-10-19T10:00:00'), mine), // lundi
      txView(tx('2', '1', '9', 30, '2026-10-21T10:00:00'), mine),
      txView(tx('3', '1', '9', 999, '2026-10-21T11:00:00', 'rejected'), mine),
      txView(tx('4', '1', '2', 50, '2026-10-21T11:00:00'), mine), // interne
      txView(tx('5', '9', '1', 70, '2026-10-21T11:00:00'), mine), // crédit
    ]
    const p = spendingPeriod(views, 'week', 0, now)
    expect(p.total).toBe(50)
    expect(p.days.map((d) => d.spent)).toEqual([20, 0, 30, 0, 0, 0, 0])
    expect(p.days.map((d) => d.future)).toEqual([false, false, false, true, true, true, true])
    expect(spendingPeriod(views, 'week', -1, now).total).toBe(0)
    expect(spendingPeriod(views, 'month', 0, now).days).toHaveLength(31)
  })

  it('destinataires : mes autres comptes puis comptes externes crédités, sans doublon', () => {
    const views = [txView(tx('1', '1', '9', 1, ''), mine), txView(tx('2', '1', '9', 1, ''), mine), txView(tx('3', '8', '1', 1, ''), mine)]
    expect(recipients([acc('1'), acc('2')], views, '1').map((r) => [r.id, r.own])).toEqual([
      ['2', true],
      ['9', false],
    ])
  })

  it('destinataires : les bénéficiaires passent avant l’historique, nommés et sans doublon', () => {
    const views = [txView(tx('1', '1', '9', 1, ''), mine), txView(tx('2', '1', '42', 1, ''), mine)]
    const lea = { id: '5', name: 'Léa Martin', accountId: '42', iban: 'FR76 9001', createdAt: null }
    const out = recipients([acc('1'), acc('2')], views, '1', [lea])
    expect(out.map((r) => [r.id, r.name, r.badge, r.short])).toEqual([
      ['2', 'Compte n°2', '#2', 'n°2'],
      ['42', 'Léa Martin', 'LM', 'Léa'],
      ['9', 'Compte n°9', '#9', 'n°9'],
    ])
  })

  it('CSV : neutralise les formules et échappe les guillemets', () => {
    expect(csvCell('=SUM(A1)')).toBe(`"'=SUM(A1)"`)
    expect(csvCell('-2+3')).toBe(`"'-2+3"`)
    expect(csvCell('dit "oui"')).toBe('"dit ""oui"""')
    const csv = historyCsv([txView(tx('1', '1', '9', 20, '2026-10-21T10:00:00'), mine, '@cmd')])
    expect(csv).toContain(`"'@cmd"`)
    expect(csv).toContain(`"'-20,00"`)
  })
})
