import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Icon } from '../components/icons'
import { EmptyState, ErrorState, LoadingState, Segmented, TxRow } from '../components/ui'
import { useShell } from '../hooks/shell-context'
import { useBankData } from '../hooks/useBankData'
import { useTxViews } from '../hooks/useTxViews'
import { groupByDay, historyCsv, signed, type TxView } from '../lib/bank'

type St = 'all' | 'ok' | 'rej'
type Dir = 'all' | 'debit' | 'credit'
const STATUS = [
  ['all', 'Tous'],
  ['ok', 'Effectués'],
  ['rej', 'Refusés'],
] as const
const DIRS = [
  ['all', 'Tous'],
  ['debit', 'Débits'],
  ['credit', 'Crédits'],
] as const

function matches(v: TxView, q: string, st: St, dir: Dir): boolean {
  if (st === 'ok' && v.rejected) return false
  if (st === 'rej' && !v.rejected) return false
  if (dir === 'debit' && v.delta >= 0) return false
  if (dir === 'credit' && v.delta <= 0) return false
  const needle = q.trim().toLowerCase()
  return !needle || `${v.title} ${v.counterpart} ${v.tx.id}`.toLowerCase().includes(needle)
}

export function HistoryPage() {
  const { transactions } = useBankData()
  const { views } = useTxViews()
  const { isDesktop, toast } = useShell()
  const navigate = useNavigate()
  const [q, setQ] = useState('')
  const [st, setSt] = useState<St>('all')
  const [dir, setDir] = useState<Dir>('all')
  const [sheet, setSheet] = useState(false)

  if (transactions.error && !views) return <ErrorState error={transactions.error} onRetry={transactions.reload} />
  if (!views) return <LoadingState label="Chargement des opérations…" />
  if (views.length === 0) return <EmptyState title="Aucune opération" text="Vos opérations apparaîtront ici dès le premier paiement." icon="history" />

  const list = views.filter((v) => matches(v, q, st, dir))
  const groups = groupByDay(list)
  const count = `${list.length} opération${list.length > 1 ? 's' : ''}`
  const active = [st !== 'all' && { label: st === 'ok' ? 'Effectués' : 'Refusés', rm: () => setSt('all') }, dir !== 'all' && { label: dir === 'debit' ? 'Débits' : 'Crédits', rm: () => setDir('all') }].filter(
    (x): x is { label: string; rm: () => void } => !!x,
  )
  const resetFilters = () => {
    setSt('all')
    setDir('all')
  }

  function exportCsv() {
    const name = `operations-${new Date().toISOString().slice(0, 10)}.csv`
    const url = URL.createObjectURL(new Blob([historyCsv(list)], { type: 'text/csv;charset=utf-8' }))
    const a = document.createElement('a')
    a.href = url
    a.download = name
    document.body.appendChild(a)
    a.click()
    a.remove()
    setTimeout(() => URL.revokeObjectURL(url), 1500)
    toast(`Fichier ${name} téléchargé`)
  }

  const search = (
    <label className="relative flex min-w-0 flex-1 items-center">
      <span className="absolute left-4 text-ink-3">
        <Icon name="search" />
      </span>
      <input type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder={isDesktop ? 'Rechercher une opération' : 'Rechercher'} aria-label="Rechercher une opération" className="search" />
    </label>
  )

  return (
    <div className="mx-auto flex w-full max-w-[820px] flex-col gap-3.5">
      {isDesktop ? (
        <>
          <div className="flex gap-2.5">
            {search}
            <button type="button" onClick={exportCsv} className="flex h-[52px] flex-none items-center gap-2 rounded-full border-0 bg-night px-[18px] text-[15px] font-semibold text-white">
              <Icon name="download" />
              <span>Exporter</span>
            </button>
          </div>
          <div className="flex flex-wrap gap-2.5">
            <Segmented label="Statut" options={STATUS} value={st} onChange={setSt} className="bg-[#e6e8eb]" />
            <Segmented label="Sens" options={DIRS} value={dir} onChange={setDir} className="bg-[#e6e8eb]" />
          </div>
        </>
      ) : (
        <>
          <div className="flex gap-2">
            {search}
            <button
              type="button"
              onClick={() => setSheet(true)}
              aria-label={`Filtres${active.length ? `, ${active.length} actifs` : ''}`}
              className={`relative grid h-[52px] w-[52px] flex-none place-items-center rounded-full border-[1.5px] ${active.length ? 'border-ink bg-night text-white' : 'border-line bg-white text-ink'}`}
            >
              <Icon name="sliders" />
              {active.length > 0 && (
                <span className="absolute -top-0.5 -right-0.5 grid h-5 min-w-5 place-items-center rounded-full border-2 border-page bg-violet-ink px-[5px] text-[11px] font-bold text-white">{active.length}</span>
              )}
            </button>
            <button type="button" onClick={exportCsv} aria-label="Exporter les opérations en CSV" className="grid h-[52px] w-[52px] flex-none place-items-center rounded-full border-0 bg-night text-white">
              <Icon name="download" />
            </button>
          </div>
          {active.length > 0 && (
            <div className="flex gap-2 overflow-x-auto pb-0.5">
              {active.map((a) => (
                <button key={a.label} type="button" onClick={a.rm} aria-label={`Retirer le filtre ${a.label}`} className="flex min-h-9 flex-none items-center gap-1.5 rounded-full border-0 bg-night py-0 pr-2 pl-3 text-[13px] font-semibold whitespace-nowrap text-white">
                  {a.label}
                  <Icon name="x" size={16} />
                </button>
              ))}
              <button type="button" onClick={resetFilters} className="min-h-9 flex-none border-0 bg-transparent px-2.5 text-[13px] font-semibold whitespace-nowrap underline">
                Tout effacer
              </button>
            </div>
          )}
        </>
      )}

      <span aria-live="polite" className="text-[13px] text-ink-3">
        {count}
      </span>

      {groups.length === 0 && (
        <div className="flex flex-col items-center gap-2.5 rounded-3xl bg-white px-5 py-9 text-center">
          <span className="text-[17px] font-semibold">Aucune opération ne correspond</span>
          <span className="text-sm text-ink-3">Modifiez la recherche ou les filtres.</span>
          <button
            type="button"
            onClick={() => {
              setQ('')
              resetFilters()
            }}
            className="btn-ghost mt-1.5 h-12 text-[15px]"
          >
            Réinitialiser les filtres
          </button>
        </div>
      )}

      {groups.map((g) => (
        <section key={g.key} aria-label={g.label} className="flex flex-col gap-1.5">
          <div className="flex justify-between px-1.5 pt-1.5">
            <h3 className="m-0 text-sm font-semibold text-ink-2">{g.label}</h3>
            <span className="tnum text-[13px] text-ink-3">{signed(g.sum)}</span>
          </div>
          <div className="rounded-3xl bg-white p-1.5 shadow-card">
            {g.items.map((v) => (
              <TxRow key={v.tx.id} view={v} onOpen={() => navigate(`/operations/${v.tx.id}`)} />
            ))}
          </div>
        </section>
      ))}

      {sheet && !isDesktop && (
        <FilterSheet count={list.length} st={st} dir={dir} setSt={setSt} setDir={setDir} onReset={resetFilters} onClose={() => setSheet(false)} />
      )}
    </div>
  )
}

function FilterSheet({
  count,
  st,
  dir,
  setSt,
  setDir,
  onReset,
  onClose,
}: {
  count: number
  st: St
  dir: Dir
  setSt: (v: St) => void
  setDir: (v: Dir) => void
  onReset: () => void
  onClose: () => void
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])
  return (
    <div className="fixed inset-0 z-[45] flex flex-col justify-end">
      <div aria-hidden onClick={onClose} className="absolute inset-0 animate-fade-in bg-[rgba(18,19,22,.45)]" />
      <div role="dialog" aria-modal="true" aria-labelledby="hf-t" className="relative flex max-h-[88%] animate-sheet-up flex-col rounded-t-[28px] bg-white shadow-[0_-20px_50px_-20px_rgba(18,19,22,.4)]">
        <div className="flex flex-none justify-center pt-2.5 pb-0.5">
          <span className="h-[5px] w-10 rounded-full bg-[#d9dce0]" />
        </div>
        <div className="flex flex-none items-center justify-between py-1.5 pr-3 pl-5">
          <h2 id="hf-t" className="m-0 text-[19px] font-bold tracking-[-0.02em]">
            Filtres
          </h2>
          <button type="button" onClick={onClose} aria-label="Fermer les filtres" className="grid h-11 w-11 place-items-center rounded-full border-0 bg-page">
            <Icon name="x" />
          </button>
        </div>
        <div className="flex min-h-0 flex-1 flex-col gap-[22px] overflow-y-auto px-5 pt-2.5 pb-4">
          <section className="flex flex-col gap-2.5">
            <h3 className="m-0 text-sm font-semibold text-ink-2">Statut</h3>
            <Segmented label="Statut" options={STATUS} value={st} onChange={setSt} stretch />
          </section>
          <section className="flex flex-col gap-2.5">
            <h3 className="m-0 text-sm font-semibold text-ink-2">Sens</h3>
            <Segmented label="Sens" options={DIRS} value={dir} onChange={setDir} stretch />
          </section>
        </div>
        <div className="grid flex-none grid-cols-[auto_minmax(0,1fr)] gap-2.5 border-t border-mute px-5 pt-3 pb-5">
          <button type="button" onClick={onReset} className="btn-ghost text-[15px]">
            Réinitialiser
          </button>
          <button type="button" onClick={onClose} className="btn-primary text-[15px]">
            Afficher {count} opération{count > 1 ? 's' : ''}
          </button>
        </div>
      </div>
    </div>
  )
}
