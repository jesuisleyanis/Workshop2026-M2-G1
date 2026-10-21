import { createContext } from 'react'
import type { Resource } from './useResource'
import type { Account, AccountLimit, AppNotification, Beneficiary, Transaction } from '../types/api'

export interface BankData {
  accounts: Resource<Account[]>
  /** Triées de la plus récente à la plus ancienne. */
  transactions: Resource<Transaction[]>
  /** Bénéficiaires enregistrés (#43) ; rechargés après ajout / suppression, pas périodiquement. */
  beneficiaries: Resource<Beneficiary[]>
  /** Plafonds mensuels (#46) ; rechargés après un virement, en cas d'échec et à la reprise du service. */
  limits: Resource<AccountLimit[]>
  /** Notifications non lues (#49) : badge de la cloche, sondé toutes les 30 s et à la reprise. */
  unreadNotifications: Resource<AppNotification[]>
  /** Libellés saisis localement (l'API n'en stocke pas), par id de transaction. */
  labels: Record<string, string>
  saveLabel: (txId: string, label: string) => void
}

export const BankDataContext = createContext<BankData | null>(null)
