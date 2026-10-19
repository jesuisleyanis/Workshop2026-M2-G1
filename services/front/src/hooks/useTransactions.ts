import { api } from '../api'
import { useResource } from './useResource'

const load = (signal: AbortSignal) => api.listTransactions(signal)

export function useTransactions() {
  return useResource(load)
}
