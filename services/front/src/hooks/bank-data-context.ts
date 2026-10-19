import { createContext } from 'react'
import type { Resource } from './useResource'
import type { Account, Transaction } from '../types/api'

export interface BankData {
  accounts: Resource<Account[]>
  /** Triées de la plus récente à la plus ancienne. */
  transactions: Resource<Transaction[]>
  /** Libellés saisis localement (l'API n'en stocke pas), par id de transaction. */
  labels: Record<string, string>
  saveLabel: (txId: string, label: string) => void
}

export const BankDataContext = createContext<BankData | null>(null)
