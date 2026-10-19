import type { Transaction } from '../types/api'
import { formatDateTime, formatMoney } from '../lib/format'

export function StatusBadge({ status }: { status: Transaction['status'] }) {
  const ok = status === 'created'
  return (
    <span className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${ok ? 'bg-emerald-100 text-emerald-800' : 'bg-red-100 text-red-800'}`}>
      {ok ? 'Acceptée' : 'Refusée'}
    </span>
  )
}

export function TransactionTable({ transactions }: { transactions: Transaction[] }) {
  if (transactions.length === 0) {
    return <p className="rounded-lg bg-white p-6 text-center text-slate-500 ring-1 ring-slate-200">Aucune transaction pour le moment.</p>
  }
  return (
    <div className="overflow-x-auto rounded-xl bg-white shadow-sm ring-1 ring-slate-200">
      <table className="w-full text-left text-sm">
        <caption className="sr-only">Historique des transactions</caption>
        <thead className="bg-slate-50 text-slate-600">
          <tr>
            <th scope="col" className="px-4 py-3 font-medium">Date</th>
            <th scope="col" className="px-4 py-3 font-medium">Bénéficiaire</th>
            <th scope="col" className="px-4 py-3 font-medium">Libellé</th>
            <th scope="col" className="px-4 py-3 text-right font-medium">Montant</th>
            <th scope="col" className="px-4 py-3 font-medium">Statut</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {transactions.map((t) => (
            <tr key={t.id}>
              <td className="whitespace-nowrap px-4 py-3">{formatDateTime(t.createdAt)}</td>
              <td className="px-4 py-3 font-mono">{t.toAccount}</td>
              <td className="px-4 py-3 text-slate-600">{t.label ?? '—'}</td>
              <td className="px-4 py-3 text-right tabular-nums">{formatMoney(t.amount, t.currency)}</td>
              <td className="px-4 py-3"><StatusBadge status={t.status} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
