import type { ScheduleFrequency, ScheduleStatus, ScheduledTransfer } from '../types/api'

/** Virements programmés (#48) : libellés et dates « YYYY-MM-DD » (sans glissement de fuseau). */
export const FREQUENCY_LABELS: Record<ScheduleFrequency, string> = {
  once: 'Une fois',
  weekly: 'Chaque semaine',
  monthly: 'Chaque mois',
}

export const STATUS_LABELS: Record<ScheduleStatus, string> = {
  active: 'Active',
  paused: 'En pause',
  cancelled: 'Annulée',
  completed: 'Terminée',
}

/** Motifs d'échec d'une exécution (mêmes refus métier qu'un virement immédiat). */
const RUN_ERRORS: Record<string, string> = {
  insufficient_funds: 'solde insuffisant',
  limit_exceeded: 'plafond mensuel atteint',
  destination_not_found: 'compte destinataire introuvable',
  account_not_found: 'compte à débiter introuvable',
  currency_mismatch: 'devises différentes',
}

export const runErrorLabel = (code: string | null) => (code && RUN_ERRORS[code]) || 'refus de la banque'

/** « Aujourd'hui » au sens du serveur (date UTC) : défaut et minimum de la date de début. */
export function todayIso(now = new Date()): string {
  return now.toISOString().slice(0, 10)
}

/** « 21 oct. 2026 » depuis « 2026-10-21 », lu à midi UTC pour ne jamais changer de jour. */
export function formatDay(iso: string | null): string {
  if (!iso || !/^\d{4}-\d{2}-\d{2}$/.test(iso)) return '—'
  const d = new Date(`${iso}T12:00:00Z`)
  return d.toLocaleDateString('fr-FR', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' })
}

/** Programmation encore modifiable (pause / reprise / annulation). */
export const isOpen = (s: ScheduledTransfer) => s.status === 'active' || s.status === 'paused'

/** Phrase d'exécution du récapitulatif : « Chaque mois à partir du 21 oct. 2026 ». */
export function whenLabel(frequency: ScheduleFrequency, startOn: string, endOn?: string | null): string {
  const start = formatDay(startOn)
  const base = frequency === 'once' ? `Le ${start}` : `${FREQUENCY_LABELS[frequency]} à partir du ${start}`
  return endOn && frequency !== 'once' ? `${base}, jusqu’au ${formatDay(endOn)}` : base
}
