import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import { BankDataContext, type BankData } from '../hooks/bank-data-context'
import { useAccounts } from '../hooks/useAccounts'
import { useBeneficiaries } from '../hooks/useBeneficiaries'
import { useLimits } from '../hooks/useLimits'
import { useUnreadCount } from '../hooks/useUnreadCount'
import { NOTIFICATIONS_POLL_MS } from '../lib/notifications'
import { useTransactions } from '../hooks/useTransactions'
import { labelStore } from '../lib/labels'

/** Rafraîchissement des soldes et opérations (onglet visible) : détecte aussi un incident sans action de l'utilisateur. */
export const REFRESH_MS = 15_000

/** Comptes + transactions partagés par toutes les pages de l'espace client, rafraîchis périodiquement. */
export function BankDataProvider({ children }: { children: ReactNode }) {
  const accounts = useAccounts()
  const transactions = useTransactions()
  const beneficiaries = useBeneficiaries()
  const limits = useLimits()
  const unreadCount = useUnreadCount()
  const { reload: reloadUnread } = unreadCount
  const { reload: reloadAccounts } = accounts
  const { reload: reloadTransactions } = transactions
  const { reload: reloadBeneficiaries, error: beneficiariesError } = beneficiaries
  const { reload: reloadLimits } = limits

  useEffect(() => {
    const id = setInterval(() => {
      if (document.visibilityState !== 'visible') return
      reloadAccounts()
      reloadTransactions()
      // Rarement modifiés : rechargés seulement s'ils ont échoué (ex. pendant un incident).
      if (beneficiariesError) reloadBeneficiaries()
      // Plafonds : dérivés des virements, rafraîchis au même rythme (autre onglet, changement de mois).
      reloadLimits()
    }, REFRESH_MS)
    return () => clearInterval(id)
  }, [reloadAccounts, reloadTransactions, reloadBeneficiaries, beneficiariesError, reloadLimits])
  useEffect(() => {
    const id = setInterval(() => {
      if (document.visibilityState === 'visible') reloadUnread()
    }, NOTIFICATIONS_POLL_MS)
    return () => clearInterval(id)
  }, [reloadUnread])
  const [labels, setLabels] = useState(labelStore.all)
  const saveLabel = useCallback((txId: string, label: string) => setLabels(labelStore.save(txId, label)), [])

  const value = useMemo<BankData>(
    () => ({ accounts, transactions, beneficiaries, limits, unreadCount, labels, saveLabel }),
    [accounts, transactions, beneficiaries, limits, unreadCount, labels, saveLabel],
  )
  return <BankDataContext.Provider value={value}>{children}</BankDataContext.Provider>
}
