import { formatClock } from '../lib/format'
import { INCIDENT_LABEL } from '../lib/state'
import { SIMULATED_TYPES, type SimulatedType } from '../lib/simulator'
import type { ConnectionStatus } from '../types/events'
import { GrafanaLinks } from './GrafanaLinks'
import { Pill, type Tone } from './Panel'

const CONN: Record<ConnectionStatus, { text: string; tone: Tone }> = {
  connecting: { text: 'Connexion…', tone: 'warn' },
  open: { text: 'Connecté', tone: 'ok' },
  reconnecting: { text: 'Reconnexion…', tone: 'warn' },
  closed: { text: 'Flux interrompu', tone: 'ko' },
}

interface Props {
  connection: ConnectionStatus
  now: number
  streamUrl: string
  simulated: boolean
  /** Simulation activée automatiquement faute de flux réel (mode `auto`). */
  fallback: boolean
  onToggleSource: () => void
  /** null : déclencheurs masqués (flux réel hors dev). */
  onTrigger: ((type: SimulatedType) => void) | null
}

export function Sidebar({ connection, now, streamUrl, simulated, fallback, onToggleSource, onTrigger }: Props) {
  const c = CONN[connection]
  return (
    <aside className="flex flex-col gap-[22px] border-edge-2 bg-side px-4 py-[22px] lg:sticky lg:top-0 lg:h-screen lg:overflow-auto lg:border-r">
      <div className="flex items-center gap-2.5 px-1.5">
        <div className="grid h-[26px] w-[26px] place-items-center rounded-[7px] bg-accent" aria-hidden>
          <div className="h-2.5 w-2.5 rotate-45 bg-side" />
        </div>
        <div className="flex flex-col">
          <span className="text-sm font-semibold tracking-[-0.01em]">Zero-Touch</span>
          <span className="text-[11px] text-mute-2">Recovery console</span>
        </div>
      </div>

      <div className="flex flex-col gap-2 rounded-xl border border-[#2a2a2f] bg-[#151517] p-3">
        <div className="flex items-center justify-between">
          <span className="text-[11px] uppercase tracking-[0.06em] text-mute-2">{simulated ? 'Simulation' : 'Flux SSE'}</span>
          <span role="status" data-testid="connection" data-status={connection}>
            <Pill tone={c.tone} className="font-mono text-[11px]">{c.text}</Pill>
          </span>
        </div>
        <div className="tnum font-mono text-[26px] font-medium tracking-[-0.02em]">{formatClock(now)}</div>
        <div className="break-all font-mono text-[11px] text-mute-3">{simulated ? 'simulation://local' : streamUrl}</div>
        {simulated && (
          <div className="rounded-md bg-warn/8 px-2 py-1.5 text-[11px] text-warn">
            {fallback ? 'Flux injoignable — simulation locale active (mêmes événements).' : 'Simulation locale — données générées dans le navigateur.'}
          </div>
        )}
        <button
          type="button"
          onClick={onToggleSource}
          className="mt-0.5 h-[30px] cursor-pointer rounded-lg border border-[#2f2f35] bg-[#1b1b1e] text-xs text-fg-2 hover:bg-[#232327]"
        >
          {simulated ? 'Réessayer le flux réel' : 'Passer en simulation'}
        </button>
      </div>

      {onTrigger && (
        <>
          <div className="h-px bg-edge-2" />
          <div className="flex flex-col gap-1">
            <span className="px-2 pb-1.5 text-xs text-mute-2">Répétition · déclencher</span>
            {SIMULATED_TYPES.map((t) => (
              <button
                key={t}
                type="button"
                onClick={() => onTrigger(t)}
                className="flex cursor-pointer flex-col items-start gap-0.5 rounded-[9px] border border-transparent px-2.5 py-1.5 text-left text-[13px] text-fg-2 hover:border-[#2a2a2f] hover:bg-[#1b1b1e]"
              >
                <span>{INCIDENT_LABEL[t]}</span>
                <span className="font-mono text-[10px] text-mute-3">{t}</span>
              </button>
            ))}
          </div>
        </>
      )}

      <div className="h-px bg-edge-2" />
      <GrafanaLinks />
    </aside>
  )
}
