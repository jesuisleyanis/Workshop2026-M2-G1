import { ErrorBanner } from '../components/ErrorBanner'
import { Spinner } from '../components/Spinner'
import { TransferForm } from '../components/TransferForm'
import { useAccounts } from '../hooks/useAccounts'

export function TransferPage() {
  const accounts = useAccounts()
  return (
    <div className="mx-auto max-w-lg space-y-4">
      <h1 className="text-2xl font-semibold text-slate-900">Virement fictif</h1>
      {accounts.loading && !accounts.data && <Spinner />}
      {accounts.error && <ErrorBanner error={accounts.error} onRetry={accounts.reload} />}
      {accounts.data && accounts.data.length > 0 && (
        <TransferForm accounts={accounts.data} onDone={accounts.reload} />
      )}
      {accounts.data && accounts.data.length === 0 && <p className="text-slate-500">Aucun compte à débiter.</p>}
    </div>
  )
}
