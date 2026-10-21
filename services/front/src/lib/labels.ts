import { decodeJwtClaims, tokenStore } from '../api/tokenStore'

const PREFIX = 'resilience.labels'
const LEGACY_KEY = PREFIX // ancienne clé commune à tous les utilisateurs de l'appareil

/**
 * Clé PAR UTILISATEUR (claim `sub` du jeton courant) : sur un poste partagé, B ne voit jamais les
 * libellés privés de A, même sur un virement qu'ils ont en commun (même id).
 */
function key(): string | null {
  const token = tokenStore.get()
  if (!token) return null
  try {
    const sub = decodeJwtClaims(token).sub
    return typeof sub === 'string' && sub ? `${PREFIX}.${sub}` : null
  } catch {
    return null
  }
}

/**
 * Libellés de virement : payment-api (TransactionIn) n'a pas de champ libellé.
 * Ils sont conservés sur l'appareil, par utilisateur, indexés par id de transaction (données fictives).
 */
export const labelStore = {
  all(): Record<string, string> {
    const k = key()
    if (!k) return {}
    try {
      localStorage.removeItem(LEGACY_KEY) // jamais réattribuée à un utilisateur : supprimée
      const v: unknown = JSON.parse(localStorage.getItem(k) ?? '{}')
      return typeof v === 'object' && v !== null && !Array.isArray(v) ? (v as Record<string, string>) : {}
    } catch {
      return {}
    }
  },
  save(txId: string, label: string): Record<string, string> {
    const next = { ...labelStore.all(), [txId]: label }
    const k = key()
    try {
      if (k) localStorage.setItem(k, JSON.stringify(next))
    } catch {
      /* stockage indisponible : libellé non persisté */
    }
    return next
  },
}
