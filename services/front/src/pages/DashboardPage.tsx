import { Link, useNavigate } from 'react-router-dom'
import { Empty, ErrorBlock, Loading, Skeleton, StatusPill, accountMap, amountTone, iconTone, txView } from '../components/ui'
import { useBankData } from '../hooks/useBankData'
import { formatIban, formatMoney } from '../lib/format'

export function DashboardPage() {
  const { accounts, transactions, labels } = useBankData()
  const navigate = useNavigate()
  const list = accounts.data ?? []
  const mine = accountMap(accounts.data)
  const total = list.reduce((s, a) => s + a.balance, 0)
  const ready = accounts.data !== null && !accounts.error

  return (
    <div className="grid items-start gap-6 [grid-template-columns:repeat(auto-fit,minmax(min(100%,340px),1fr))]">
      <section aria-label="Comptes" className="flex min-w-0 flex-col gap-5">
        <div className="flex flex-col gap-1.5">
          <span className="text-[13px] text-ink-3">Solde total</span>
          <span data-testid="balance" className="tnum text-[clamp(38px,5vw,56px)] font-semibold leading-none tracking-[-0.045em]">
            {ready ? formatMoney(total, list[0]?.currency) : '—'}
          </span>
          <span className="text-[13px] text-ink-3">
            {ready ? `${list.length} compte${list.length > 1 ? 's' : ''}` : accounts.loading ? 'Chargement…' : ''}
          </span>
        </div>

        {accounts.loading && !accounts.data && (
          <div role="status" aria-label="Chargement des comptes…" className="grid gap-3.5 [grid-template-columns:repeat(auto-fill,minmax(230px,1fr))]">
            <Skeleton className="h-44 rounded-[20px]" />
            <Skeleton className="h-44 rounded-[20px]" />
          </div>
        )}
        {accounts.error && <ErrorBlock title="Impossible de charger vos comptes" error={accounts.error} onRetry={accounts.reload} />}
        {ready && list.length === 0 && <Empty>Aucun compte n'est rattaché à cet utilisateur.</Empty>}
        {ready && list.length > 0 && (
          <div className="grid gap-3.5 [grid-template-columns:repeat(auto-fill,minmax(230px,1fr))]">
            {list.map((a) => (
              <button
                key={a.id}
                type="button"
                onClick={() => navigate('/accounts')}
                className="flex min-h-44 cursor-pointer flex-col justify-between gap-6 rounded-[20px] bg-night p-5 text-left text-[#f3f4f6] hover:bg-[#24262c]"
              >
                <span className="flex items-center justify-between">
                  <span className="text-[13px] text-[#a7abb3]">Compte #{a.id}</span>
                  <span className="rounded-md bg-night-3 px-2 py-0.5 text-[11px]">{a.currency}</span>
                </span>
                {a.iban && <span className="break-words font-mono text-[13px] text-[#d5d8de]">{formatIban(a.iban)}</span>}
                <span className="flex flex-col gap-0.5">
                  <span className="text-xs text-[#a7abb3]">Solde disponible</span>
                  <span className="tnum text-[26px] font-semibold tracking-[-0.03em]">{formatMoney(a.balance, a.currency)}</span>
                </span>
              </button>
            ))}
          </div>
        )}
      </section>

      <section aria-labelledby="recent-title" className="flex min-w-0 flex-col gap-1.5 rounded-[20px] bg-soft p-5">
        <div className="flex items-center justify-between pb-1.5">
          <h2 id="recent-title" className="text-[17px] font-semibold tracking-tight">Dernières opérations</h2>
          <Link to="/history" className="text-[13px] text-ink-2 underline underline-offset-[3px]">Tout voir</Link>
        </div>
        {transactions.loading && !transactions.data && <Loading label="Chargement des opérations…" count={3} className="h-12" />}
        {transactions.error && <ErrorBlock title="Impossible de charger les opérations" error={transactions.error} onRetry={transactions.reload} />}
        {transactions.data?.length === 0 && (
          <div className="flex flex-col gap-2.5 py-5 text-sm text-ink-3">
            <span>Aucune opération pour le moment.</span>
            <Link to="/transfer" className="inline-flex h-10 items-center self-start rounded-[11px] border-[1.5px] border-night px-4 font-semibold text-ink">
              Faire un premier virement
            </Link>
          </div>
        )}
        {transactions.data?.slice(0, 6).map((t) => {
          const v = txView(t, mine, t.label ?? labels[t.id])
          return (
            <div key={t.id} className="grid grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-3.5 border-b border-[#e6e8ec] py-3">
              <div className={`grid h-[38px] w-[38px] place-items-center rounded-xl ${iconTone[v.tone]}`} aria-hidden>{v.glyph}</div>
              <div className="flex min-w-0 flex-col gap-0.5">
                <span className="truncate text-sm font-semibold">{v.title}</span>
                <span className="truncate text-xs text-ink-3">{v.dateShort} · {v.sub}</span>
              </div>
              <div className="flex flex-col items-end gap-1">
                <span className={`tnum text-[15px] font-semibold ${amountTone[v.tone]}`}>{v.amount}</span>
                <StatusPill status={t.status} />
              </div>
            </div>
          )
        })}
      </section>
    </div>
  )
}
