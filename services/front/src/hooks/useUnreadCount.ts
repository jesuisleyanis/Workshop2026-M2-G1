import { api } from '../api'
import { useResource } from './useResource'

const load = (signal: AbortSignal) => api.getUnreadCount(signal)

export function useUnreadCount() {
  return useResource(load)
}
