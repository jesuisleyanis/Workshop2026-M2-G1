import { api } from '../api'
import { useResource } from './useResource'

const load = (signal: AbortSignal) => api.getLimits(signal)

export function useLimits() {
  return useResource(load)
}
