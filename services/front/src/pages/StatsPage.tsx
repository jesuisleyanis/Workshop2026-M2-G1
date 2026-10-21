import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Icon } from '../components/icons'
import { Card, EmptyState, ErrorState, H2, LoadingState, Segmented, TxRow } from '../components/ui'
import { useBankData } from '../hooks/useBankData'
import { useTxViews } from '../hooks/useTxViews'
import { dayKey, spendingPeriod, type StatsMode } from '../lib/bank'
import { formatMoney } from '../lib/format'

const MODES = [
  ['week', 'Semaine'],
  ['month', 'Mois'],
] as const
const WEEKDAYS = ['Lun', 'Mar', 'Mer', 'Jeu', 'Ven', 'Sam', 'Dim']

export function StatsPage() {
  const { transactions } = useBankData()
  const { views } = useTxViews()
  const navigate = useNavigate()
  const [mode, setMode] = useState<StatsMode>('week')
  const [offset, setOffset] = useState(0)

  if (transactions.error && !views) return <ErrorState error={transactions.error} onRetry={transactions.reload} />
  if (!views) return <LoadingState label="Chargement des statistiques…" />
  if (views.length === 0) return <EmptyState title="Aucune dépense" text="Vos statistiques apparaîtront après vos premières opérations." icon="chart" />

  const p = spendingPeriod(views, mode, offset)
  const week = mode === 'week'
  const max = Math.max(1, ...p.days.map((d) => d.spent))
  const today = dayKey(new Date().toISOString())
  const first = p.days[0]!.key
  const last = p.days[p.days.length - 1]!.key
  const ops = views.filter((v) => {
    const k = dayKey(v.tx.createdAt)
    return k >= first && k <= last
  })
  const aria = `Graphique des dépenses par jour, ${p.label}. ${p.days
    .filter((d) => !d.future)
    .map((d) => `${d.date.toLocaleDateString('fr-FR', { weekday: 'short', day: 'numeric' })} ${formatMoney(d.spent)}`)
    .join(', ')}.`

  return (
    <div className="flex flex-col gap-5">
      <Card className="gap-[18px] p-5">
        <div className="flex flex-wrap items-start justify-between gap-3.5">
          <div className="flex flex-col gap-1">
            <span className="text-sm font-medium text-ink-3">Total dépensé</span>
            <span data-testid="stats-total" className="tnum text-[34px] font-bold tracking-[-0.03em]">
              {p.total > 0 ? '−' : ''}
              {formatMoney(p.total)}
            </span>
          </div>
          <Segmented
            label="Période"
            options={MODES}
            value={mode}
            onChange={(m) => {
              setMode(m)
              setOffset(0)
            }}
          />
        </div>
        <div className="flex items-center gap-2.5">
          <button type="button" aria-label="Période précédente" onClick={() => setOffset((o) => o - 1)} className="grid h-11 w-11 flex-none place-items-center rounded-full border-[1.5px] border-line bg-white">
            <Icon name="back" />
          </button>
          <span aria-live="polite" className="flex-1 text-center text-[15px] font-semibold">
            {p.label}
          </span>
          <button
            type="button"
            aria-label="Période suivante"
            disabled={offset >= 0}
            onClick={() => setOffset((o) => o + 1)}
            className="grid h-11 w-11 flex-none place-items-center rounded-full border-[1.5px] border-line bg-white disabled:opacity-35"
          >
            <Icon name="chev" />
          </button>
        </div>
        <div role="img" aria-label={aria} className={`flex h-[184px] items-end ${week ? 'gap-3' : 'gap-[3px]'}`}>
          {p.days.map((d, i) => {
            const h = d.future ? 6 : Math.max(8, Math.round((d.spent / max) * 150))
            const label = week ? WEEKDAYS[i] : [1, 8, 15, 22, 29].includes(d.date.getDate()) ? String(d.date.getDate()) : ''
            return (
              <div
                key={d.key}
                title={`${d.date.toLocaleDateString('fr-FR', { weekday: 'short', day: 'numeric', month: 'short' })} : ${formatMoney(d.spent)}`}
                className="flex h-full min-w-0 flex-1 flex-col items-center justify-end gap-2"
              >
                <div
                  className={`w-full max-w-[38px] ${week ? 'rounded-xl' : 'rounded-[4px]'} ${d.future ? 'bg-[#e6e8eb]' : d.key === today ? 'bg-violet' : 'bg-[#c9bcff]'}`}
                  style={{ height: h }}
                />
                <span aria-hidden className="h-[15px] text-xs leading-[15px] text-ink-3">
                  {label}
                </span>
              </div>
            )
          })}
        </div>
      </Card>

      <Card aria-labelledby="h-pop" className="gap-1 px-3 pt-[18px] pb-2.5">
        <H2 id="h-pop" className="px-2 pb-2">
          Opérations de la période
        </H2>
        {ops.length === 0 ? (
          <p className="m-0 px-2 py-6 text-center text-[15px] text-ink-3">Aucune opération enregistrée sur cette période.</p>
        ) : (
          ops.map((v) => <TxRow key={v.tx.id} view={v} onOpen={() => navigate(`/operations/${v.tx.id}`)} />)
        )}
      </Card>
    </div>
  )
}
