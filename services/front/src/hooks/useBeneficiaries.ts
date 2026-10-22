import { api } from '../api'
import { useResource } from './useResource'

const load = (signal: AbortSignal) => api.listBeneficiaries(signal)

export function useBeneficiaries() {
  return useResource(load)
}
