import { formatClock } from '../lib/format'
import type { ConnectionStatus } from '../types/events'

const CONN: Record<ConnectionStatus, { text: string; dot: string }> = {
  connecting: { text: 'Connexion…', dot: 'bg-amber-400 animate-pulse' },
  open: { text: 'Flux temps réel actif', dot: 'bg-emerald-400' },
  reconnecting: { text: 'Reconnexion…', dot: 'bg-amber-400 animate-pulse' },
  closed: { text: 'Flux interrompu', dot: 'bg-red-500' },
}

interface Props {
  connection: ConnectionStatus
  now: number
  rejected: number
  onReset: () => void
}

export function Header({ connection, now, rejected, onReset }: Props) {
  const c = CONN[connection]
  return (
    <header className="flex flex-wrap items-center justify-between gap-4">
      <div>
        <h1 className="text-3xl font-black tracking-tight text-slate-50 xl:text-4xl">RESILIENCE-ALPHA</h1>
        <p className="text-base text-slate-400">Supervision &middot; reprise autonome (Zero-Touch Recovery)</p>
      </div>
      <div className="flex items-center gap-5">
        {rejected > 0 && (
          <span className="rounded-md bg-amber-500/15 px-2 py-1 text-sm text-amber-300" title="Messages du flux rejetés (non conformes au contrat)">
            {rejected} message{rejected > 1 ? 's' : ''} rejeté{rejected > 1 ? 's' : ''}
          </span>
        )}
        <p role="status" data-testid="connection" data-status={connection} className="flex items-center gap-2 text-base font-semibold text-slate-200">
          <span className={`h-3 w-3 rounded-full ${c.dot}`} aria-hidden />
          {c.text}
        </p>
        <p className="font-mono text-3xl font-bold tabular-nums text-slate-100">{formatClock(now)}</p>
        <button
          type="button"
          onClick={onReset}
          className="rounded-lg border border-slate-700 px-3 py-1.5 text-sm text-slate-400 hover:border-slate-500 hover:text-slate-200"
          title="Remet la vue à l'état AVANT (reprise de clip)"
        >
          Réinitialiser la vue
        </button>
      </div>
    </header>
  )
}
