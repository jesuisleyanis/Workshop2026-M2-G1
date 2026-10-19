import { useCallback, useMemo, useReducer } from 'react'
import { derivePhase, initialState, reducer } from '../lib/state'
import type { ConnectionStatus, StreamMessage } from '../types/events'
import { useRemediationStream, type EventSourceFactory } from './useRemediationStream'

/** État du dashboard alimenté par le flux SSE du moteur de remédiation. */
export function useDashboard(streamUrl: string, factory?: EventSourceFactory) {
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

  const reset = useCallback(() => dispatch({ type: 'reset' }), [])
  return { state, phase: derivePhase(state), reset }
}
