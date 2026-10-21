import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api'
import { Icon } from '../components/icons'
import { Alert, EmptyState, ErrorState, LoadingState } from '../components/ui'
import { useBankData } from '../hooks/useBankData'
import { useShell } from '../hooks/shell-context'
import { accountName } from '../lib/bank'
import { PERIOD_PRESETS, presetRange, printPath, statementError, type PeriodPreset } from '../lib/statements'

/** D14 — Relevés : compte + période, export CSV (via le client authentifié) et version imprimable (#50). */
export function StatementsPage() {
  const { accounts } = useBankData()
  const { toast } = useShell()
  const navigate = useNavigate()
  const [picked, setPicked] = useState<string | null>(null)
  const [preset, setPreset] = useState<PeriodPreset | 'custom'>('month')
  const [custom, setCustom] = useState(() => presetRange('month'))
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  if (accounts.error && !accounts.data) return <ErrorState error={accounts.error} onRetry={accounts.reload} />
  if (!accounts.data) return <LoadingState label="Chargement des comptes…" />
  if (accounts.data.length === 0) return <EmptyState title="Aucun compte" text="Aucun relevé disponible pour le moment." icon="download" />

  const acc = accounts.data.find((a) => a.id === picked) ?? accounts.data[0]!
  const range = preset === 'custom' ? custom : presetRange(preset)
  const query = { accountId: acc.id, ...range }

  const download = async () => {
    setBusy(true)
    setErr(null)
    try {
      const name = await api.downloadStatement(query)
      toast(`Relevé téléchargé (${name})`)
    } catch (e) {
      setErr(statementError(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="mx-auto flex w-full max-w-[620px] flex-col gap-4">
      <div role="group" aria-label="Compte" className="flex gap-2 overflow-x-auto pb-1">
        {accounts.data.map((a) => (
          <button
            key={a.id}
            type="button"
            aria-pressed={a.id === acc.id}
            onClick={() => setPicked(a.id)}
            className={`min-h-11 flex-none rounded-full border-[1.5px] px-4 text-sm font-semibold whitespace-nowrap ${a.id === acc.id ? 'border-ink bg-night text-white' : 'border-line bg-white text-ink'}`}
          >
            {accountName(a.id)}
          </button>
        ))}
      </div>

      <section aria-label="Période" className="card flex flex-col gap-3.5 p-[18px]">
        <div role="group" aria-label="Raccourcis de période" className="flex flex-wrap gap-2">
          {[...PERIOD_PRESETS, { id: 'custom' as const, label: 'Personnalisée' }].map((p) => (
            <button
              key={p.id}
              type="button"
              aria-pressed={preset === p.id}
              onClick={() => {
                if (p.id === 'custom' && preset !== 'custom') setCustom(range)
                setPreset(p.id)
              }}
              className={`min-h-11 rounded-full border-[1.5px] px-4 text-sm font-semibold ${preset === p.id ? 'border-ink bg-night text-white' : 'border-line bg-white text-ink'}`}
            >
              {p.label}
            </button>
          ))}
        </div>
        {preset === 'custom' && (
          <div className="grid grid-cols-2 gap-3">
            <label className="flex flex-col gap-1.5 text-sm font-medium text-ink-2">
              Du
              <input type="date" value={custom.from} onChange={(e) => setCustom((c) => ({ ...c, from: e.target.value }))} className="field" />
            </label>
            <label className="flex flex-col gap-1.5 text-sm font-medium text-ink-2">
              Au
              <input type="date" value={custom.to} onChange={(e) => setCustom((c) => ({ ...c, to: e.target.value }))} className="field" />
            </label>
          </div>
        )}
        <p data-testid="statement-range" className="m-0 text-sm text-ink-3">
          Du {range.from} au {range.to} (inclus, dates UTC)
        </p>
      </section>

      {err && <Alert>{err}</Alert>}
      <div className="grid grid-cols-2 gap-2.5">
        <button type="button" disabled={busy} onClick={() => void download()} className="btn-primary">
          <Icon name="download" size={18} />
          {busy ? 'Téléchargement…' : 'Télécharger CSV'}
        </button>
        <button type="button" onClick={() => navigate(printPath(query))} className="btn-ghost">
          <Icon name="print" size={18} />
          Version imprimable
        </button>
      </div>
      <p className="m-0 text-center text-[13px] text-ink-3">Période de 12 mois au plus. Données fictives — démonstrateur pédagogique.</p>
    </div>
  )
}
