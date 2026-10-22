import { api } from '../api'
import { useResource } from './useResource'

const load = (signal: AbortSignal) => api.listCards(signal)

/** Cartes (#47) : chargées par l'écran qui les affiche, pas par le BankDataProvider. */
export function useCards() {
  return useResource(load)
}
