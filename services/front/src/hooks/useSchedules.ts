import { api } from '../api'
import { useResource } from './useResource'

const load = (signal: AbortSignal) => api.listSchedules(signal)

/** Virements programmés (#48) : chargés par l'écran qui les affiche, pas par le BankDataProvider. */
export function useSchedules() {
  return useResource(load)
}
