import { ApiError } from '../api/errors'
import type { StatementQuery } from '../types/api'
import { userMessage } from './errorMessages'

/** Relevés (#50) : périodes en jours UTC, comme le serveur. */
export type PeriodPreset = 'month' | 'last_month' | 'three_months'

export const PERIOD_PRESETS: { id: PeriodPreset; label: string }[] = [
  { id: 'month', label: 'Ce mois-ci' },
  { id: 'last_month', label: 'Mois dernier' },
  { id: 'three_months', label: '3 derniers mois' },
]

const iso = (d: Date) => d.toISOString().slice(0, 10)
const utc = (y: number, m: number, d: number) => new Date(Date.UTC(y, m, d))

/** Bornes incluses [from, to] d'un raccourci de période, calculées en UTC. */
export function presetRange(preset: PeriodPreset, now = new Date()): { from: string; to: string } {
  const y = now.getUTCFullYear()
  const m = now.getUTCMonth()
  if (preset === 'last_month') return { from: iso(utc(y, m - 1, 1)), to: iso(utc(y, m, 0)) }
  if (preset === 'three_months') return { from: iso(utc(y, m - 2, 1)), to: iso(now) }
  return { from: iso(utc(y, m, 1)), to: iso(now) }
}

export function statementPath(q: StatementQuery, format: 'csv' | 'json'): string {
  const p = new URLSearchParams({ account_id: q.accountId, from: q.from, to: q.to, format })
  return `/api/v1/statements?${p.toString()}`
}

export function printPath(q: StatementQuery): string {
  return `/statements/print?${new URLSearchParams({ account: q.accountId, from: q.from, to: q.to }).toString()}`
}

const ERRORS: Record<string, string> = {
  invalid_period: 'Période invalide : la date de fin doit suivre le début, sur 12 mois au plus.',
  statement_too_large: 'Trop d’opérations sur cette période : réduisez-la pour exporter le relevé.',
  account_not_found: 'Ce compte n’existe pas ou n’est pas accessible.',
}

export function statementError(e: unknown): string {
  return (e instanceof ApiError && ERRORS[e.code]) || userMessage(e)
}

/** Déclenche le téléchargement d'un fichier (URL blob, compatible CSP) puis libère l'URL. */
export function saveFile(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.rel = 'noopener'
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 0)
}
