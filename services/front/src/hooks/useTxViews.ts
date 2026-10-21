import { useMemo } from 'react'
import { txView, type TxView } from '../lib/bank'
import { useBankData } from './useBankData'

/** Transactions vues depuis le client (sens, libellé local), plus récentes d'abord. null tant que non chargées. */
export function useTxViews(): { mine: ReadonlySet<string>; views: TxView[] | null } {
  const { accounts, transactions, labels } = useBankData()
  return useMemo(() => {
    const mine = new Set((accounts.data ?? []).map((a) => a.id))
    const views = transactions.data ? transactions.data.map((t) => txView(t, mine, labels[t.id])) : null
    return { mine, views }
  }, [accounts.data, transactions.data, labels])
}
