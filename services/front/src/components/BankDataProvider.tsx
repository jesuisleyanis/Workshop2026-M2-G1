import { useCallback, useMemo, useState, type ReactNode } from 'react'
import { BankDataContext, type BankData } from '../hooks/bank-data-context'
import { useAccounts } from '../hooks/useAccounts'
import { useTransactions } from '../hooks/useTransactions'
import { labelStore } from '../lib/labels'

/** Comptes + transactions chargés une fois pour toutes les pages de l'espace client. */
export function BankDataProvider({ children }: { children: ReactNode }) {
  const accounts = useAccounts()
  const transactions = useTransactions()
  const [labels, setLabels] = useState(labelStore.all)
  const saveLabel = useCallback((txId: string, label: string) => setLabels(labelStore.save(txId, label)), [])

  const value = useMemo<BankData>(
    () => ({ accounts, transactions, labels, saveLabel }),
    [accounts, transactions, labels, saveLabel],
  )
  return <BankDataContext.Provider value={value}>{children}</BankDataContext.Provider>
}
