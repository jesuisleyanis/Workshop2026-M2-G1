import type { AccountLimit } from '../types/api'

/** Part restante du plafond (0–1), null si sans plafond (#46). */
export function remainingShare(l: AccountLimit): number | null {
  if (l.limit === null || l.remaining === null) return null
  if (l.limit <= 0) return 0
  return Math.min(1, Math.max(0, l.remaining / l.limit))
}

/** « 1 nov. » : `periodEnd` est une date calendaire (UTC), lue à midi pour ne pas glisser de jour. */
export function resetLabel(periodEnd: string): string {
  const d = new Date(`${periodEnd}T12:00:00Z`)
  return Number.isNaN(d.getTime()) ? '—' : d.toLocaleDateString('fr-FR', { day: 'numeric', month: 'long' })
}

/** Le montant saisi dépasse-t-il le plafond restant connu ? (avertissement seulement : le serveur décide). */
export function exceedsLimit(l: AccountLimit | undefined, amount: number): boolean {
  return !!l && l.remaining !== null && amount > l.remaining
}
