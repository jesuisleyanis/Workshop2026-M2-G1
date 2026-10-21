import { useCallback } from 'react'
import { useParams } from 'react-router-dom'
import { api } from '../api'
import { ApiError } from '../api/errors'
import { Icon } from '../components/icons'
import { EmptyState, ErrorState, LoadingState } from '../components/ui'
import { useShell } from '../hooks/shell-context'
import { copyText } from '../lib/clipboard'
import { useBankData } from '../hooks/useBankData'
import { useResource } from '../hooks/useResource'
import { useTxViews } from '../hooks/useTxViews'
import { accountName, signed, txView, type TxView } from '../lib/bank'
import { categoryLabel } from '../lib/categories'
import { formatMoney, formatTime, maskIban } from '../lib/format'
import type { Account, Beneficiary } from '../types/api'

const NOT_FOUND = <EmptyState title="Opération introuvable" text="Cette opération n’existe plus ou n’est pas accessible." icon="history" />

/** « Compte n°1 · FR76 •••• •••• 0001 … » : mes comptes et mes bénéficiaires ont un IBAN connu. */
function accountLine(id: string, accounts: Account[], beneficiaries: Beneficiary[]): string {
  const own = accounts.find((a) => a.id === id)
  if (own?.iban) return `${accountName(id)} · ${maskIban(own.iban)}`
  const b = beneficiaries.find((x) => x.accountId === id)
  return b ? `${b.name} · ${maskIban(b.iban)}` : accountName(id)
}

export function TxDetailPage() {
  const { id = '' } = useParams()
  const { transactions } = useBankData()
  const { views } = useTxViews()

  if (transactions.error && !views) return <ErrorState error={transactions.error} onRetry={transactions.reload} />
  if (!views) return <LoadingState label="Chargement de l’opération…" />
  const v = views.find((x) => x.tx.id === id)
  // Hors des 50 dernières (lien direct, opération ancienne) : GET /api/v1/transactions/{id} (#45).
  return v ? <TxDetail view={v} /> : <FetchedTxDetail id={id} />
}

function FetchedTxDetail({ id }: { id: string }) {
  const { labels } = useBankData()
  const { mine } = useTxViews()
  const tx = useResource(useCallback((signal: AbortSignal) => api.getTransaction(id, signal), [id]))
  if (tx.error && !tx.data) {
    if (tx.error instanceof ApiError && (tx.error.status === 404 || tx.error.status === 422)) return NOT_FOUND
    return <ErrorState error={tx.error} onRetry={tx.reload} />
  }
  if (!tx.data) return <LoadingState label="Chargement de l’opération…" />
  return <TxDetail view={txView(tx.data, mine, labels[tx.data.id])} />
}

function TxDetail({ view: v }: { view: TxView }) {
  const { accounts, beneficiaries } = useBankData()
  const { toast } = useShell()
  const line = (accId: string) => accountLine(accId, accounts.data ?? [], beneficiaries.data ?? [])
  const { tx, rejected, direction } = v
  const date = tx.createdAt ? new Date(tx.createdAt) : null
  const when =
    date && !Number.isNaN(date.getTime())
      ? `${date.toLocaleDateString('fr-FR', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' }).replace(/^./, (c) => c.toUpperCase())} à ${formatTime(tx.createdAt)}`
      : '—'
  const ref = tx.requestId ?? `#${tx.id}`
  const rows: [string, string][] = [
    ['Sens', direction === 'internal' ? 'Virement interne' : direction === 'out' ? 'Débit (sortant)' : 'Crédit (entrant)'],
    ['Date et heure', when],
    ['Compte débité', line(tx.fromAccount)],
    ['Compte crédité', line(tx.toAccount)],
    ...(tx.category ? [['Catégorie', categoryLabel(tx.category)] as [string, string]] : []),
    ['Libellé', v.title],
  ]
  const amount = direction === 'internal' ? formatMoney(tx.amount, tx.currency) : signed(v.delta, tx.currency)
  const color = rejected ? 'text-ink-3 line-through' : v.delta > 0 ? 'text-ok-fg' : 'text-ink'

  return (
    <div className="card mx-auto flex w-full max-w-[620px] flex-col gap-[18px] p-6">
      <div className="flex flex-col items-center gap-2 text-center">
        <span className="grid h-16 w-16 place-items-center rounded-[20px] border border-line bg-[#d8f2f7] text-[#0e6b80]">
          <Icon name={rejected ? 'x' : direction === 'in' ? 'inArrow' : direction === 'out' ? 'outArrow' : 'swap'} size={28} />
        </span>
        <span className="text-[17px] font-semibold">{v.title}</span>
        <span data-testid="tx-amount" className={`tnum text-[40px] font-bold tracking-[-0.03em] ${color}`}>
          {amount}
        </span>
        <span className={`rounded-full px-3 py-1.5 text-[13px] font-bold ${rejected ? 'bg-ko-bg text-ko-fg' : 'bg-ok-bg text-[#14532d]'}`}>{rejected ? 'Refusé' : 'Effectué'}</span>
      </div>
      <dl className="m-0 flex flex-col">
        {rows.map(([k, val]) => (
          <div key={k} className="flex justify-between gap-4 border-t border-mute py-[13px]">
            <dt className="flex-none text-sm text-ink-3">{k}</dt>
            <dd className="m-0 text-right text-[15px] font-semibold">{val}</dd>
          </div>
        ))}
        <div className="flex items-center justify-between gap-3 border-t border-mute py-2">
          <dt className="text-sm text-ink-3">Référence</dt>
          <dd className="m-0 flex items-center gap-1.5">
            <span className="font-mono text-[13px]">{ref}</span>
            <button
              type="button"
              aria-label="Copier la référence"
              onClick={() => void copyText(ref).then((ok) => toast(ok ? 'Référence copiée' : 'Copie impossible : notez la référence'))}
              className="grid h-11 w-11 place-items-center rounded-xl border-0 bg-page"
            >
              <Icon name="copy" size={16} />
            </button>
          </dd>
        </div>
      </dl>
    </div>
  )
}
