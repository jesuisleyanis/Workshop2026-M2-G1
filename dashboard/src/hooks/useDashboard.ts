import { useCallback, useMemo, useReducer } from 'react'
import { derivePhase, initialState, reducer } from '../lib/state'
import type { ConnectionStatus, StreamMessage } from '../types/events'
import { usePrometheusPolling } from './usePrometheusPolling'
import { useRemediationStream, type EventSourceFactory } from './useRemediationStream'

/**
 * État du dashboard : flux SSE du moteur (incidents) + polling Prometheus (score, santé).
 * `metricsBase` null/vide = pas de polling (simulation, tests).
 */
export function useDashboard(streamUrl: string, factory?: EventSourceFactory, metricsBase: string | null = null, pollMs = 2000) {
  const [state, dispatch] = useReducer(reducer, initialState)

  const handlers = useMemo(
    () => ({
      onMessage: (message: StreamMessage) => dispatch({ type: 'message', message }),
      onRejected: () => dispatch({ type: 'rejected' }),
      onStatus: (status: ConnectionStatus) => dispatch({ type: 'connection', status }),
    }),
    [],
  )
  useRemediationStream(streamUrl, handlers, factory)
  usePrometheusPolling(metricsBase, handlers.onMessage, pollMs)

  const reset = useCallback(() => dispatch({ type: 'reset' }), [])
  return { state, phase: derivePhase(state), reset }
}
