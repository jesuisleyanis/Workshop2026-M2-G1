import { api } from '../api'
import { useResource } from './useResource'

const load = (signal: AbortSignal) => api.getAccounts(signal)

export function useAccounts() {
  return useResource(load)
}
