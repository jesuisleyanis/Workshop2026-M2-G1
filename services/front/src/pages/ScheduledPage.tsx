import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api'
import { ApiError } from '../api/errors'
import { Icon } from '../components/icons'
import { Alert, ConfirmDialog, EmptyState, ErrorState, LoadingState } from '../components/ui'
import { useBankData } from '../hooks/useBankData'
import { useSchedules } from '../hooks/useSchedules'
import { useShell } from '../hooks/shell-context'
import { accountName } from '../lib/bank'
import { userMessage } from '../lib/errorMessages'
import { formatMoney } from '../lib/format'
import { FREQUENCY_LABELS, STATUS_LABELS, formatDay, isOpen, runErrorLabel } from '../lib/schedules'
import type { ScheduledTransfer } from '../types/api'

const actionError = (e: unknown) =>
  e instanceof ApiError && e.code === 'schedule_closed'
    ? 'Cette programmation est déjà annulée ou terminée.'
    : e instanceof ApiError && e.code === 'schedule_not_found'
      ? 'Cette programmation n’existe plus ou n’est pas accessible.'
      : userMessage(e)

const PILL: Record<ScheduledTransfer['status'], string> = {
  active: 'bg-ok-bg text-[#14532d]',
  paused: 'bg-page text-ink-2',
  cancelled: 'bg-mute text-ink-3',
  completed: 'bg-mute text-ink-3',
}

/** D12 — Virements programmés : liste, exécution échouée, pause / reprise, annulation confirmée (#48). */
export function ScheduledPage() {
  const schedules = useSchedules()
  const { accounts, beneficiaries } = useBankData()
  const { toast } = useShell()
  const navigate = useNavigate()
  const [cancelling, setCancelling] = useState<ScheduledTransfer | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)

  if (schedules.error && !schedules.data) return <ErrorState error={schedules.error} onRetry={schedules.reload} />
  if (!schedules.data) return <LoadingState label="Chargement des virements programmés…" />

  const nameOf = (id: string) => beneficiaries.data?.find((b) => b.accountId === id)?.name ?? accountName(id)
  const currency = (id: string) => accounts.data?.find((a) => a.id === id)?.currency ?? 'EUR'

  const run = async (s: ScheduledTransfer, action: () => Promise<unknown>, done: string) => {
    setBusy(s.id)
    setErr(null)
    try {
      await action()
      toast(done)
    } catch (e) {
      setErr(actionError(e))
    } finally {
      setBusy(null)
      schedules.reload()
    }
  }

  const newButton = (
    <button type="button" onClick={() => navigate('/send')} className="btn-primary min-h-12 self-start px-4">
      <Icon name="plus" size={18} />
      Programmer un virement
    </button>
  )

  return (
    <div className="mx-auto flex w-full max-w-[620px] flex-col gap-4">
      {newButton}
      {err && <Alert>{err}</Alert>}
      {schedules.data.length === 0 ? (
        <EmptyState title="Aucun virement programmé" text="Depuis Envoyer, choisissez « Programmer » pour un virement unique, hebdomadaire ou mensuel." icon="clock" />
      ) : (
        <ul aria-label="Virements programmés" className="m-0 flex list-none flex-col gap-3 p-0">
          {schedules.data.map((s) => {
            const failed = s.lastRun?.status === 'failed'
            return (
              <li key={s.id} className="card flex flex-col gap-3 p-[18px]">
                <div className="flex items-start justify-between gap-3">
                  <span className="flex min-w-0 flex-col gap-0.5">
                    <span className="truncate text-[15px] font-semibold">{nameOf(s.toAccount)}</span>
                    <span className="text-[13px] text-ink-3">
                      {FREQUENCY_LABELS[s.frequency]} · depuis {accountName(s.fromAccount)}
                    </span>
                  </span>
                  <span className="flex flex-none flex-col items-end gap-1">
                    <span className="tnum text-lg font-bold">{formatMoney(s.amount, currency(s.fromAccount))}</span>
                    <span className={`rounded-full px-2.5 py-1 text-xs font-bold ${PILL[s.status]}`}>{STATUS_LABELS[s.status]}</span>
                  </span>
                </div>
                <dl className="m-0 grid grid-cols-2 gap-x-4 gap-y-1 text-[13px]">
                  <dt className="text-ink-3">Prochaine exécution</dt>
                  <dd className="m-0 text-right font-semibold">{isOpen(s) ? formatDay(s.nextRunOn) : '—'}</dd>
                  <dt className="text-ink-3">Fin</dt>
                  <dd className="m-0 text-right font-semibold">{s.frequency === 'once' ? 'Unique' : s.endOn ? formatDay(s.endOn) : 'Sans fin'}</dd>
                </dl>
                {failed && (
                  <Alert tone="warn">
                    Dernière exécution échouée le {formatDay(s.lastRun!.runOn)} : {runErrorLabel(s.lastRun!.errorCode)}.
                  </Alert>
                )}
                {s.lastRun?.status === 'pending' && (
                  <Alert tone="info">
                    Exécution du {formatDay(s.lastRun.runOn)} interrompue (service redémarré) : elle ne sera pas rejouée automatiquement, vérifiez l’historique.
                  </Alert>
                )}
                {isOpen(s) && (
                  <div className="flex gap-2.5">
                    {s.status === 'active' ? (
                      <button type="button" disabled={busy === s.id} onClick={() => void run(s, () => api.setScheduleStatus(s.id, 'paused'), 'Programmation mise en pause')} className="btn-ghost min-h-11 flex-1">
                        Mettre en pause
                      </button>
                    ) : (
                      <button type="button" disabled={busy === s.id} onClick={() => void run(s, () => api.setScheduleStatus(s.id, 'active'), 'Programmation reprise')} className="btn-ghost min-h-11 flex-1">
                        Reprendre
                      </button>
                    )}
                    <button type="button" disabled={busy === s.id} onClick={() => setCancelling(s)} className="btn-ghost min-h-11 flex-1 text-ko-fg">
                      Annuler
                    </button>
                  </div>
                )}
              </li>
            )
          })}
        </ul>
      )}
      {cancelling && (
        <ConfirmDialog
          title="Annuler ce virement programmé ?"
          text={`Plus aucune exécution vers ${nameOf(cancelling.toAccount)}. Les virements déjà exécutés sont conservés.`}
          confirmLabel="Annuler la programmation"
          icon="x"
          danger
          onConfirm={() => {
            const s = cancelling
            setCancelling(null)
            void run(s, () => api.cancelSchedule(s.id), 'Programmation annulée')
          }}
          onCancel={() => setCancelling(null)}
        />
      )}
    </div>
  )
}
