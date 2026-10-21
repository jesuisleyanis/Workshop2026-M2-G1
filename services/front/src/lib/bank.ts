import { formatMoney } from './format'
import type { Account, Transaction } from '../types/api'

/**
 * Vues métier dérivées de /accounts et /transactions (fonctions pures, testées dans bank.test.ts).
 * payment-api n'expose ni nom de compte, ni contrepartie nommée, ni catégorie : on affiche des
 * libellés neutres (« Compte n°12 ») plutôt que d'inventer des données.
 */

const GRADIENTS = [
  'linear-gradient(140deg,#2a2c32 0%,#121316 58%,#1d1f24 100%)',
  'linear-gradient(140deg,#8b6bff 0%,#5b34e0 60%,#3f1fb8 100%)',
  'linear-gradient(140deg,#1fb7a0 0%,#0f8a7a 60%,#0b6359 100%)',
]

/** Pastilles d'avatar [fond, encre]. */
const AVATARS: [string, string][] = [
  ['#dde9ff', '#1d4fb8'],
  ['#fde2ef', '#a3195b'],
  ['#d9f4ea', '#0f7a55'],
  ['#ffe8d6', '#b24a00'],
  ['#ebe3ff', '#5b34c4'],
  ['#fff3c4', '#8a6400'],
]

export const accountName = (id: string) => `Compte n°${id}`
export const accountGradient = (index: number) => GRADIENTS[index % GRADIENTS.length]!
export const avatarTone = (index: number) => AVATARS[index % AVATARS.length]!

export function last4(iban: string | null, fallbackId: string): string {
  const raw = (iban ?? '').replace(/\s+/g, '')
  return raw.length >= 4 ? raw.slice(-4) : fallbackId.padStart(4, '0')
}

export const maskCard = (a: Account) => `•••• •••• •••• ${last4(a.iban, a.id)}`

export function initials(name: string): string {
  return name
    .split(/[\s._-]+/)
    .filter(Boolean)
    .map((w) => w[0]!)
    .join('')
    .slice(0, 2)
    .toUpperCase()
}

export const signed = (n: number, currency = 'EUR') => (n < 0 ? '−' : '+') + formatMoney(Math.abs(n), currency)

/** Transaction vue depuis le client : sens, montant signé (null = virement interne), contrepartie. */
export interface TxView {
  tx: Transaction
  direction: 'out' | 'in' | 'internal'
  /** Montant signé en euros : négatif = débit. Interne = 0 sur le total. */
  delta: number
  counterpart: string
  title: string
  rejected: boolean
}

export function txView(t: Transaction, mine: ReadonlySet<string>, label?: string | null): TxView {
  const out = mine.has(t.fromAccount)
  const inc = mine.has(t.toAccount)
  const direction = out && inc ? 'internal' : out ? 'out' : 'in'
  const counterpart =
    direction === 'internal'
      ? `${accountName(t.fromAccount)} → n°${t.toAccount}`
      : accountName(direction === 'out' ? t.toAccount : t.fromAccount)
  const fallback = direction === 'internal' ? 'Virement interne' : direction === 'out' ? 'Virement émis' : 'Virement reçu'
  const delta = direction === 'internal' ? 0 : direction === 'out' ? -t.amount : t.amount
  return { tx: t, direction, delta, counterpart, title: label || t.label || fallback, rejected: t.status === 'rejected' }
}

export function dayKey(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1)

/** « Aujourd'hui », « Hier » ou « Lundi 19 octobre ». */
export function dayLabel(key: string, now = new Date()): string {
  if (!key) return 'Date inconnue'
  const today = dayKey(now.toISOString())
  const y = new Date(now)
  y.setDate(y.getDate() - 1)
  if (key === today) return "Aujourd'hui"
  if (key === dayKey(y.toISOString())) return 'Hier'
  const d = new Date(`${key}T00:00`)
  return cap(d.toLocaleDateString('fr-FR', { weekday: 'long', day: 'numeric', month: 'long' }))
}

export interface DayGroup {
  key: string
  label: string
  /** Somme des mouvements effectués (hors rejetés). */
  sum: number
  items: TxView[]
}

/** Regroupe par jour en conservant l'ordre (le plus récent d'abord). */
export function groupByDay(items: TxView[], now = new Date()): DayGroup[] {
  const groups: DayGroup[] = []
  for (const v of items) {
    const key = dayKey(v.tx.createdAt)
    let g = groups.find((x) => x.key === key)
    if (!g) {
      g = { key, label: dayLabel(key, now), sum: 0, items: [] }
      groups.push(g)
    }
    g.items.push(v)
    if (!v.rejected) g.sum += v.delta
  }
  return groups
}

export type StatsMode = 'week' | 'month'

export interface StatsPeriod {
  label: string
  days: { key: string; date: Date; future: boolean; spent: number }[]
  total: number
}

/** Dépenses (débits effectués vers l'extérieur) par jour sur la semaine (lun→dim) ou le mois, décalés de `offset`. */
export function spendingPeriod(views: TxView[], mode: StatsMode, offset: number, now = new Date()): StatsPeriod {
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  const dates: Date[] = []
  let label: string
  if (mode === 'week') {
    const monday = new Date(today)
    monday.setDate(today.getDate() - ((today.getDay() + 6) % 7) + offset * 7)
    for (let i = 0; i < 7; i++) dates.push(new Date(monday.getFullYear(), monday.getMonth(), monday.getDate() + i))
    const end = dates[6]!
    label = `Du ${monday.toLocaleDateString('fr-FR', { day: 'numeric', month: 'short' })} au ${end.toLocaleDateString('fr-FR', { day: 'numeric', month: 'short', year: 'numeric' })}`
  } else {
    const first = new Date(today.getFullYear(), today.getMonth() + offset, 1)
    const n = new Date(first.getFullYear(), first.getMonth() + 1, 0).getDate()
    for (let i = 0; i < n; i++) dates.push(new Date(first.getFullYear(), first.getMonth(), i + 1))
    label = cap(first.toLocaleDateString('fr-FR', { month: 'long', year: 'numeric' }))
  }
  const byDay = new Map<string, number>()
  for (const v of views) {
    if (v.rejected || v.direction !== 'out') continue
    const k = dayKey(v.tx.createdAt)
    byDay.set(k, (byDay.get(k) ?? 0) + v.tx.amount)
  }
  const days = dates.map((date) => {
    const key = dayKey(date.toISOString())
    return { key, date, future: date > today, spent: byDay.get(key) ?? 0 }
  })
  return { label, days, total: days.reduce((s, d) => s + d.spent, 0) }
}

/** Neutralise l'injection de formules dans un tableur (=, +, -, @, tabulation, retour chariot). */
export function csvCell(v: string): string {
  const safe = /^[=+\-@\t\r]/.test(v) ? `'${v}` : v
  return `"${safe.replace(/"/g, '""')}"`
}

export function toCsv(rows: string[][]): string {
  return '﻿' + rows.map((r) => r.map(csvCell).join(';')).join('\n')
}

export function historyCsv(views: TxView[]): string {
  return toCsv([
    ['Date', 'Libellé', 'Contrepartie', 'Montant (EUR)', 'Statut', 'Référence'],
    ...views.map((v) => [
      v.tx.createdAt.replace('T', ' ').slice(0, 19),
      v.title,
      v.counterpart,
      v.delta.toFixed(2).replace('.', ','),
      v.rejected ? 'Refusé' : 'Effectué',
      v.tx.requestId ?? `#${v.tx.id}`,
    ]),
  ])
}

export interface Recipient {
  /** Id de compte payment-api (dst_account). */
  id: string
  name: string
  mask: string
  own: boolean
}

/** Destinataires connus : mes autres comptes puis les comptes externes déjà crédités (en attendant les bénéficiaires, #43). */
export function recipients(accounts: Account[], views: TxView[], excludeId?: string): Recipient[] {
  const out: Recipient[] = accounts
    .filter((a) => a.id !== excludeId)
    .map((a) => ({ id: a.id, name: accountName(a.id), mask: `•••• ${last4(a.iban, a.id)} · vous`, own: true }))
  const seen = new Set(accounts.map((a) => a.id))
  for (const v of views) {
    const id = v.tx.toAccount
    if (v.direction !== 'out' || seen.has(id)) continue
    seen.add(id)
    out.push({ id, name: accountName(id), mask: `Compte n°${id}`, own: false })
  }
  return out
}

/** Pastille d'avatar d'un compte : « 12 », « #7 ». */
export const accountBadge = (id: string) => (id.length <= 2 ? `#${id}` : id.slice(-3))
