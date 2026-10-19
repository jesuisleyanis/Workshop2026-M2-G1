import { ErrorBanner } from '../components/ErrorBanner'
import { Spinner } from '../components/Spinner'
import { TransactionTable } from '../components/TransactionTable'
import { useTransactions } from '../hooks/useTransactions'

export function HistoryPage() {
  const txs = useTransactions()
  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold text-slate-900">Historique</h1>
        <button type="button" onClick={txs.reload} className="rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm hover:bg-slate-50">Actualiser</button>
      </div>
      {txs.loading && !txs.data && <Spinner label="Chargement de l'historique…" />}
      {txs.error && <ErrorBanner error={txs.error} onRetry={txs.reload} />}
      {txs.data && <TransactionTable transactions={txs.data} />}
    </div>
  )
}
