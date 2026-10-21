import { useCallback } from 'react'
import { api } from '../api'
import { useResource } from './useResource'

/** Répartition des dépenses de la période EN COURS (GET /api/v1/stats/spending, #44). */
export function useSpending(period: 'week' | 'month') {
  const load = useCallback((signal: AbortSignal) => api.getSpending(period, signal), [period])
  return useResource(load)
}
