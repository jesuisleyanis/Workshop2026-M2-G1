import { api } from '../api'
import { useResource } from './useResource'
import type { Transaction } from '../types/api'

/** Plus récente d'abord : created_at si présent, sinon id numérique décroissant. */
export function byMostRecent(a: Transaction, b: Transaction): number {
  if (a.createdAt && b.createdAt && a.createdAt !== b.createdAt) return b.createdAt.localeCompare(a.createdAt)
  return Number(b.id) - Number(a.id) || b.id.localeCompare(a.id)
}

const load = async (signal: AbortSignal) => [...(await api.listTransactions(signal))].sort(byMostRecent)

export function useTransactions() {
  return useResource(load)
}
