import { useState } from 'react'
import { Empty, ErrorBlock, Loading, StatusPill, accountMap, amountTone, iconTone, txView } from '../components/ui'
import { useBankData } from '../hooks/useBankData'
import type { TransactionStatus } from '../types/api'

type Filter = 'all' | TransactionStatus
const FILTERS: [Filter, string][] = [
  ['all', 'Toutes'],
  ['created', 'Effectuées'],
  ['rejected', 'Rejetées'],
]
const COLS = 'grid-cols-[96px_minmax(0,1.5fr)_minmax(0,0.9fr)_76px_minmax(96px,auto)]'

export function HistoryPage() {
  const { accounts, transactions, labels } = useBankData()
  const [filter, setFilter] = useState<Filter>('all')
  const all = transactions.data ?? []
  const mine = accountMap(accounts.data)
  const matches = (f: Filter) => all.filter((t) => f === 'all' || t.status === f)
  const list = matches(filter)

  return (
    <section aria-label="Historique des opérations" className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div role="group" aria-label="Filtrer par statut" className="flex gap-1 rounded-[13px] bg-[#f2f3f5] p-1">
          {FILTERS.map(([k, label]) => (
            <button
              key={k}
              type="button"
              aria-pressed={filter === k}
              onClick={() => setFilter(k)}
              className={`flex h-[38px] cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-[10px] px-3.5 text-sm font-medium ${filter === k ? 'bg-white shadow-sm' : 'text-[#5b5f66]'}`}
            >
              {label} <span className="tnum opacity-60">{matches(k).length}</span>
            </button>
          ))}
        </div>
        <button type="button" className="btn-ghost h-10" disabled={transactions.loading} onClick={transactions.reload}>
          {transactions.loading ? 'Actualisation…' : 'Actualiser'}
        </button>
      </div>

      {transactions.loading && !transactions.data && <Loading label="Chargement de l'historique…" count={4} className="h-14" />}
      {transactions.error && <ErrorBlock title="Impossible de charger l'historique" error={transactions.error} onRetry={transactions.reload} />}
      {transactions.data && list.length === 0 && (
        <Empty>{all.length ? 'Aucune opération ne correspond à ce filtre.' : "Aucune opération pour l'instant. Vos virements apparaîtront ici."}</Empty>
      )}
      {list.length > 0 && (
        <div className="overflow-x-auto">
          <div role="table" aria-label="Opérations" className="flex min-w-[500px] flex-col">
            <div role="row" className={`grid ${COLS} gap-3.5 border-b border-[#e6e8ec] px-1 pb-2.5 text-xs text-ink-3`}>
              <span role="columnheader">Date</span>
              <span role="columnheader">Opération</span>
              <span role="columnheader" className="whitespace-nowrap">Bénéficiaire</span>
              <span role="columnheader">Statut</span>
              <span role="columnheader" className="text-right">Montant</span>
            </div>
            {list.map((t) => {
              const v = txView(t, mine, t.label ?? labels[t.id])
              return (
                <div role="row" key={t.id} className={`grid ${COLS} items-center gap-3.5 border-b border-[#eef0f2] px-1 py-3.5 text-sm`}>
                  <div role="cell" className="flex flex-col gap-0.5">
                    <span>{v.date}</span>
                    <span className="text-xs text-ink-4">{v.time}</span>
                  </div>
                  <div role="cell" className="flex min-w-0 items-center gap-3">
                    <div className={`grid h-[34px] w-[34px] flex-none place-items-center rounded-[11px] ${iconTone[v.tone]}`} aria-hidden>{v.glyph}</div>
                    <div className="flex min-w-0 flex-col gap-0.5">
                      <span className="truncate font-semibold">{v.title}</span>
                      <span className="truncate text-xs text-ink-3">{v.sub}</span>
                    </div>
                  </div>
                  <div role="cell" className="flex min-w-0 flex-col gap-0.5">
                    <span className="font-mono text-[13px]">#{t.toAccount}</span>
                    <span className="truncate font-mono text-[11px] text-ink-4">{v.dstDetail}</span>
                  </div>
                  <span role="cell" className="justify-self-start"><StatusPill status={t.status} /></span>
                  <span role="cell" className={`tnum whitespace-nowrap text-right font-semibold ${amountTone[v.tone]}`}>{v.amount}</span>
                </div>
              )
            })}
          </div>
        </div>
      )}
    </section>
  )
}
