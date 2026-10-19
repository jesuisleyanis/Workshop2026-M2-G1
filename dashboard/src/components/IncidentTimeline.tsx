import { INCIDENT_LABEL, buildTimeline } from '../lib/state'
import { formatOffset, formatTime } from '../lib/format'
import type { Incident, TimelineStepStatus } from '../types/events'
import { Panel } from './Panel'

const STATUS_UI: Record<TimelineStepStatus, { text: string; dot: string; badge: string }> = {
  pending: { text: 'EN ATTENTE', dot: 'border-slate-700 bg-slate-900 text-slate-600', badge: 'text-slate-500' },
  active: { text: 'EN COURS', dot: 'border-amber-400 bg-amber-500/20 text-amber-200 animate-pulse', badge: 'text-amber-300' },
  done: { text: 'TERMINÉ', dot: 'border-emerald-400 bg-emerald-500/20 text-emerald-200', badge: 'text-emerald-300' },
  failed: { text: 'ÉCHEC', dot: 'border-red-400 bg-red-500/25 text-red-100', badge: 'text-red-300' },
}

export function IncidentTimeline({ incident }: { incident: Incident | null }) {
  if (!incident) {
    return (
      <Panel title="Timeline d'incident">
        <p className="py-10 text-center text-xl text-slate-500">Aucun incident - la plateforme fonctionne normalement.</p>
      </Panel>
    )
  }
  const steps = buildTimeline(incident)
  const top = incident.anomaly?.features_top.slice(0, 3) ?? []

  return (
    <Panel
      title="Timeline d'incident"
      aside={<span className="rounded-full bg-slate-800 px-3 py-1 text-sm font-semibold text-slate-200">{INCIDENT_LABEL[incident.incidentType]}</span>}
    >
      <ol className="space-y-3" aria-label="Étapes de la remédiation">
        {steps.map((s, idx) => {
          const ui = STATUS_UI[s.status]
          return (
            <li key={s.id} data-step={s.id} data-status={s.status} className="flex items-start gap-4">
              <span className={`mt-1 flex h-11 w-11 shrink-0 items-center justify-center rounded-full border-2 text-lg font-black ${ui.dot}`} aria-hidden>
                {s.status === 'done' ? '✓' : s.status === 'failed' ? '✕' : idx + 1}
              </span>
              <div className="min-w-0 flex-1 border-b border-slate-800 pb-3">
                <div className="flex flex-wrap items-baseline gap-x-4">
                  <p className="text-2xl font-bold text-slate-100">{s.label}</p>
                  <p className={`text-sm font-bold tracking-widest ${ui.badge}`}>{ui.text}</p>
                  {s.ts && (
                    <p className="ml-auto font-mono text-lg tabular-nums text-slate-300">
                      {formatTime(s.ts)} <span className="text-slate-500">{formatOffset(s.offsetSeconds)}</span>
                    </p>
                  )}
                </div>
                <p className="mt-0.5 text-base text-slate-400">{s.detail}</p>
              </div>
            </li>
          )
        })}
      </ol>
      {top.length > 0 && (
        <div className="mt-4 flex flex-wrap items-center gap-2 text-sm text-slate-400">
          <span className="uppercase tracking-wider">Signaux dominants</span>
          {top.map((f) => (
            <span key={f.name} className="rounded-md bg-slate-800 px-2 py-1 font-mono text-slate-200">
              {f.name} z={f.z.toFixed(1)}
            </span>
          ))}
        </div>
      )}
    </Panel>
  )
}
