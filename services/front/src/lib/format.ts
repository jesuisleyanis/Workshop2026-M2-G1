export function formatMoney(amount: number, currency = 'EUR'): string {
  try {
    return new Intl.NumberFormat('fr-FR', { style: 'currency', currency }).format(amount)
  } catch {
    return `${amount.toFixed(2)} ${currency}`
  }
}

function toDate(iso: string): Date | null {
  if (!iso) return null
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? null : d
}

export function formatDateTime(iso: string): string {
  const d = toDate(iso)
  return d ? new Intl.DateTimeFormat('fr-FR', { dateStyle: 'medium', timeStyle: 'short' }).format(d) : '—'
}

/** « 21 oct. 2026 » ; « — » si l'horodatage est absent ou illisible. */
export function formatDate(iso: string): string {
  const d = toDate(iso)
  return d ? d.toLocaleDateString('fr-FR', { day: '2-digit', month: 'short', year: 'numeric' }) : '—'
}

export function formatDateShort(iso: string): string {
  const d = toDate(iso)
  return d ? d.toLocaleDateString('fr-FR', { day: 'numeric', month: 'short' }) : '—'
}

export function formatTime(iso: string): string {
  const d = toDate(iso)
  return d ? d.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' }) : ''
}

/** Regroupe un IBAN par blocs de 4 caractères. */
export function formatIban(iban: string): string {
  return iban.replace(/\s+/g, '').replace(/(.{4})/g, '$1 ').trim()
}

/**
 * IBAN masqué pour un écran partageable (#45) : pays + clé, code banque (2e groupe) et 4e groupe
 * restent lisibles — dans le seed, le 2e distingue un client (0000) d'un tiers (9999) et le 4e
 * numérote le compte. Le reste est masqué.
 */
export function maskIban(iban: string): string {
  const groups = formatIban(iban).split(' ')
  if (groups.length <= 3) return groups.join(' ')
  const keep = new Set([0, 1, Math.min(3, groups.length - 1)])
  return groups.map((g, i) => (keep.has(i) ? g : '•'.repeat(g.length))).join(' ')
}

/** « FR76 … 0142 » pour les espaces contraints. */
export function shortIban(iban: string): string {
  const x = iban.replace(/\s+/g, '')
  return x.length > 8 ? `${x.slice(0, 4)} … ${x.slice(-4)}` : x
}

/** Montant -> valeur de champ de saisie (« 1250,50 »). */
export function amountToInput(amount: number): string {
  return amount.toFixed(2).replace('.', ',')
}
