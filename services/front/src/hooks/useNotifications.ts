import { useCallback } from 'react'
import { api } from '../api'
import { useResource } from './useResource'

/** Notifications (#49) : `unread` pour le badge de la cloche, toutes pour la page. */
export function useNotifications(unread: boolean) {
  const load = useCallback((signal: AbortSignal) => api.listNotifications(unread, signal), [unread])
  return useResource(load)
}
