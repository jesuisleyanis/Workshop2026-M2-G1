import { formatDuration } from '../lib/format'
import { incidentMttr } from '../lib/state'
import type { Incident } from '../types/events'
import { Panel } from './Panel'

interface Props {
  incident: Incident | null
  /** Horloge (ms epoch) pour le compteur live. */
  now: number
}

function Metric({ label, hint, value, live }: { label: string; hint: string; value: string; live?: boolean }) {
  return (
    <div>
      <p className="text-lg font-bold text-slate-200">
        {label} <span className="text-sm font-normal text-slate-500">{hint}</span>
      </p>
      <p className={`text-5xl font-black tabular-nums ${value === '--' ? 'text-slate-600' : live ? 'text-amber-300' : 'text-emerald-300'}`} data-testid={`metric-${label.toLowerCase()}`}>
        {value}
      </p>
      {live && <p className="text-sm font-semibold tracking-widest text-amber-300">EN COURS</p>}
    </div>
  )
}

export function MetricsCards({ incident, now }: Props) {
  const open = incident !== null && incident.verification === null && incident.failure === null
  const mttr = incident ? incidentMttr(incident) : null
  const live = open && incident ? Math.max(0, (now - Date.parse(incident.detectedAt)) / 1000) : null

  return (
    <Panel title="Indicateurs de reprise">
      <div className="grid grid-cols-2 gap-6">
        <Metric label="MTTD" hint="détection" value={formatDuration(incident?.mttdSeconds ?? null)} />
        <Metric label="MTTR" hint="rétablissement" value={formatDuration(live ?? mttr)} live={live !== null} />
      </div>
    </Panel>
  )
}
