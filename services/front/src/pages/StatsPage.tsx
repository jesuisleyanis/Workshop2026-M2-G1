import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Icon } from '../components/icons'
import { Card, EmptyState, ErrorState, H2, LoadingState, Segmented, TxRow } from '../components/ui'
import { useBankData } from '../hooks/useBankData'
import { useSpending } from '../hooks/useSpending'
import { useTxViews } from '../hooks/useTxViews'
import { dayKey, spendingPeriod, type StatsMode } from '../lib/bank'
import { categoryInfo, formatShare } from '../lib/categories'
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

      <CategoriesCard mode={mode} past={offset < 0} />

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

/** D8 : répartition par catégorie, calculée par payment-api pour la période en cours (pas de calcul local inventé). */
function CategoriesCard({ mode, past }: { mode: StatsMode; past: boolean }) {
  const spending = useSpending(mode)
  const current = mode === 'week' ? 'cette semaine' : 'ce mois-ci'
  let body
  if (spending.error && !spending.data) {
    body = (
      <div role="alert" className="flex flex-col items-start gap-2 px-2 py-4 text-sm text-ink-3">
        Répartition indisponible pour le moment.
        <button type="button" onClick={spending.reload} className="btn-ghost h-10 text-sm">
          Réessayer
        </button>
      </div>
    )
  } else if (!spending.data) {
    body = <div role="status" aria-label="Chargement des catégories…" className="h-24 animate-sk rounded-2xl bg-[#eef0f2]" />
  } else if (spending.data.byCategory.length === 0) {
    body = <p className="m-0 px-2 py-6 text-center text-[15px] text-ink-3">Aucune dépense {current}.</p>
  } else {
    body = (
      <ul aria-label="Dépenses par catégorie" className="m-0 flex list-none flex-col gap-3 p-0 px-2">
        {spending.data.byCategory.map((c) => {
          const info = categoryInfo(c.category)
          return (
            <li key={c.category} className="flex items-center gap-3">
              <span className="grid h-10 w-10 flex-none place-items-center rounded-xl text-white" style={{ background: info.tone }}>
                <Icon name={info.icon} size={18} />
              </span>
              <span className="flex min-w-0 flex-1 flex-col gap-1.5">
                <span className="flex justify-between gap-2 text-[15px]">
                  <span className="font-semibold">{info.label}</span>
                  <span className="tnum font-semibold">{formatMoney(c.amount)}</span>
                </span>
                <span className="flex items-center gap-2.5">
                  <span className="block h-2 flex-1 overflow-hidden rounded-full bg-mute">
                    <span className="block h-full rounded-full" style={{ width: `${Math.round(c.share * 100)}%`, background: info.tone }} />
                  </span>
                  <span className="tnum w-11 text-right text-[13px] text-ink-3">{formatShare(c.share)}</span>
                </span>
              </span>
            </li>
          )
        })}
      </ul>
    )
  }
  return (
    <Card aria-labelledby="h-cat" className="gap-3 px-3 pt-[18px] pb-4">
      <div className="flex items-baseline justify-between gap-3 px-2">
        <H2 id="h-cat">Catégories</H2>
        {spending.data && spending.data.total > 0 && <span className="tnum text-sm font-semibold text-ink-2">{formatMoney(spending.data.total)}</span>}
      </div>
      {past && <p className="m-0 px-2 text-[13px] text-ink-3">Répartition de la période en cours ({current}).</p>}
      {body}
    </Card>
  )
}
