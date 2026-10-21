import { useCallback } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api } from '../api'
import { Icon } from '../components/icons'
import { ErrorState, LoadingState } from '../components/ui'
import { useBankData } from '../hooks/useBankData'
import { useResource } from '../hooks/useResource'
import { accountName } from '../lib/bank'
import { ADDRESS, BANK, BIC } from '../lib/bankInfo'
import { categoryLabel } from '../lib/categories'
import { formatDateTime, formatIban, formatMoney } from '../lib/format'
import { statementError } from '../lib/statements'

/** D14 — Relevé imprimable : en-tête banque, titulaire, période, opérations, totaux (CSS print, sans lib PDF). */
export function StatementPrintPage() {
  const [params] = useSearchParams()
  const { labels } = useBankData()
  const accountId = params.get('account') ?? ''
  const from = params.get('from') ?? ''
  const to = params.get('to') ?? ''
  const st = useResource(useCallback((signal: AbortSignal) => api.getStatement({ accountId, from, to }, signal), [accountId, from, to]))

  if (st.error && !st.data) return <ErrorState error={st.error} title={statementError(st.error)} onRetry={st.reload} />
  if (!st.data) return <LoadingState label="Préparation du relevé…" />
  const s = st.data

  return (
    <div className="mx-auto flex w-full max-w-[860px] flex-col gap-4">
      <div className="flex justify-end">
        <button type="button" onClick={() => window.print()} className="btn-primary">
          <Icon name="print" size={18} />
          Imprimer
        </button>
      </div>
      <section data-print aria-label="Relevé de compte" className="card flex flex-col gap-4 p-6 text-[14px]">
        <header className="flex flex-wrap justify-between gap-4 border-b border-mute pb-4">
          <div className="flex flex-col">
            <strong className="text-lg">{BANK}</strong>
            <span className="text-ink-3">{ADDRESS}</span>
            <span className="font-mono text-ink-3">BIC {BIC}</span>
          </div>
          <div className="flex flex-col text-right">
            <strong className="text-lg">Relevé de compte</strong>
            <span>
              Du {s.from} au {s.to}
            </span>
          </div>
        </header>
        <dl className="m-0 grid grid-cols-2 gap-2">
          <div>
            <dt className="text-ink-3">Titulaire</dt>
            <dd className="m-0 font-semibold">{s.holder}</dd>
          </div>
          <div>
            <dt className="text-ink-3">{accountName(s.accountId)}</dt>
            <dd className="m-0 font-mono">{formatIban(s.iban)}</dd>
          </div>
        </dl>
        {s.rows.length === 0 ? (
          <p className="m-0 text-ink-3">Aucune opération sur cette période.</p>
        ) : (
          <table className="w-full border-collapse text-left">
            <thead>
              <tr className="border-b border-line text-ink-3">
                <th className="py-2 font-medium">Date</th>
                <th className="py-2 font-medium">Libellé</th>
                <th className="py-2 font-medium">Catégorie</th>
                <th className="py-2 text-right font-medium">Débit</th>
                <th className="py-2 text-right font-medium">Crédit</th>
                <th className="py-2 text-right font-medium">Statut</th>
              </tr>
            </thead>
            <tbody>
              {s.rows.map((r) => {
                const rejected = r.status === 'rejected'
                const label = labels[r.id] ?? (r.direction === 'debit' ? `Virement vers ${accountName(r.counterpartyAccount)}` : `Virement de ${accountName(r.counterpartyAccount)}`)
                return (
                  <tr key={r.id} data-testid="statement-row" className={`border-b border-mute ${rejected ? 'text-ink-3 line-through' : ''}`}>
                    <td className="py-1.5 whitespace-nowrap">{formatDateTime(r.createdAt)}</td>
                    <td className="py-1.5">
                      {label} <span className="font-mono text-[12px] text-ink-3">{r.reference}</span>
                    </td>
                    <td className="py-1.5">{r.category ? categoryLabel(r.category) : '—'}</td>
                    <td className="tnum py-1.5 text-right">{r.direction === 'debit' ? formatMoney(r.amount) : ''}</td>
                    <td className="tnum py-1.5 text-right">{r.direction === 'credit' ? formatMoney(r.amount) : ''}</td>
                    <td className="py-1.5 text-right">{rejected ? 'Refusé' : 'Effectué'}</td>
                  </tr>
                )
              })}
            </tbody>
            <tfoot>
              <tr className="font-semibold">
                <td colSpan={3} className="py-2">
                  Totaux (opérations effectuées)
                </td>
                <td data-testid="total-debit" className="tnum py-2 text-right">
                  {formatMoney(s.totalDebit)}
                </td>
                <td data-testid="total-credit" className="tnum py-2 text-right">
                  {formatMoney(s.totalCredit)}
                </td>
                <td />
              </tr>
            </tfoot>
          </table>
        )}
        <p className="m-0 text-[12px] text-ink-3">Document fictif — démonstrateur pédagogique, sans valeur contractuelle.</p>
      </section>
    </div>
  )
}
