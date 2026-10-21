import { useCallback, useEffect } from 'react'
import { api } from '../api'
import { useResource } from './useResource'
import { useServiceStatus } from './useServiceStatus'

/** Répartition des dépenses d'une période (GET /api/v1/stats/spending, #44) ; offset 0 = en cours. */
export function useSpending(period: 'week' | 'month', offset = 0) {
  const load = useCallback((signal: AbortSignal) => api.getSpending(period, offset, signal), [period, offset])
  const resource = useResource(load)
  const status = useServiceStatus()
  const { reload } = resource
  // Comme les données du BankDataProvider : rechargée sans action à la reprise du service.
  useEffect(() => {
    if (status === 'restored') reload()
  }, [status, reload])
  return resource
}
