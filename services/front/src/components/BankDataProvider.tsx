import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import { BankDataContext, type BankData } from '../hooks/bank-data-context'
import { useAccounts } from '../hooks/useAccounts'
import { useBeneficiaries } from '../hooks/useBeneficiaries'
import { useTransactions } from '../hooks/useTransactions'
import { labelStore } from '../lib/labels'

/** Rafraîchissement des soldes et opérations (onglet visible) : détecte aussi un incident sans action de l'utilisateur. */
export const REFRESH_MS = 15_000

/** Comptes + transactions partagés par toutes les pages de l'espace client, rafraîchis périodiquement. */
export function BankDataProvider({ children }: { children: ReactNode }) {
  const accounts = useAccounts()
  const transactions = useTransactions()
  const beneficiaries = useBeneficiaries()
  const { reload: reloadAccounts } = accounts
  const { reload: reloadTransactions } = transactions
  const { reload: reloadBeneficiaries, error: beneficiariesError } = beneficiaries

  useEffect(() => {
    const id = setInterval(() => {
      if (document.visibilityState !== 'visible') return
      reloadAccounts()
      reloadTransactions()
      // Rarement modifiés : rechargés seulement s'ils ont échoué (ex. pendant un incident).
      if (beneficiariesError) reloadBeneficiaries()
    }, REFRESH_MS)
    return () => clearInterval(id)
  }, [reloadAccounts, reloadTransactions, reloadBeneficiaries, beneficiariesError])
  const [labels, setLabels] = useState(labelStore.all)
  const saveLabel = useCallback((txId: string, label: string) => setLabels(labelStore.save(txId, label)), [])

  const value = useMemo<BankData>(
    () => ({ accounts, transactions, beneficiaries, labels, saveLabel }),
    [accounts, transactions, beneficiaries, labels, saveLabel],
  )
  return <BankDataContext.Provider value={value}>{children}</BankDataContext.Provider>
}
