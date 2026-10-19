import { Link } from 'react-router-dom'
import { BalanceCard } from '../components/BalanceCard'
import { ErrorBanner } from '../components/ErrorBanner'
import { Spinner } from '../components/Spinner'
import { TransactionTable } from '../components/TransactionTable'
import { useAccounts } from '../hooks/useAccounts'
import { useTransactions } from '../hooks/useTransactions'

export function DashboardPage() {
  const accounts = useAccounts()
  const txs = useTransactions()

  return (
    <div className="space-y-8">
      <section aria-labelledby="accounts-title" className="space-y-4">
        <h1 id="accounts-title" className="text-2xl font-semibold text-slate-900">Mes comptes</h1>
        {accounts.loading && !accounts.data && <Spinner label="Chargement des comptes…" />}
        {accounts.error && <ErrorBanner error={accounts.error} onRetry={accounts.reload} />}
        {accounts.data && accounts.data.length === 0 && <p className="text-slate-500">Aucun compte.</p>}
        <div className="grid gap-4 sm:grid-cols-2">
          {accounts.data?.map((a) => <BalanceCard key={a.id} account={a} />)}
        </div>
        <Link to="/transfer" className="inline-block rounded-lg bg-teal-700 px-4 py-2 font-medium text-white hover:bg-teal-800">Nouveau virement</Link>
      </section>

      <section aria-labelledby="recent-title" className="space-y-4">
        <h2 id="recent-title" className="text-lg font-semibold text-slate-900">Dernières opérations</h2>
        {txs.loading && !txs.data && <Spinner label="Chargement des opérations…" />}
        {txs.error && <ErrorBanner error={txs.error} onRetry={txs.reload} />}
        {txs.data && <TransactionTable transactions={txs.data.slice(0, 5)} />}
      </section>
    </div>
  )
}
