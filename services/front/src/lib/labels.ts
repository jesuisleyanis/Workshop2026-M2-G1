const KEY = 'resilience.labels'

/**
 * Libellés de virement : payment-api (TransactionIn) n'a pas de champ libellé.
 * Ils sont conservés sur l'appareil, indexés par id de transaction (données fictives, non sensibles).
 */
export const labelStore = {
  all(): Record<string, string> {
    try {
      const v: unknown = JSON.parse(localStorage.getItem(KEY) ?? '{}')
      return typeof v === 'object' && v !== null && !Array.isArray(v) ? (v as Record<string, string>) : {}
    } catch {
      return {}
    }
  },
  save(txId: string, label: string): Record<string, string> {
    const next = { ...labelStore.all(), [txId]: label }
    try {
      localStorage.setItem(KEY, JSON.stringify(next))
    } catch {
      /* stockage indisponible : libellé non persisté */
    }
    return next
  },
}
