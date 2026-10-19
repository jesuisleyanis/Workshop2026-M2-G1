import { INCIDENT_LABEL, buildTimeline } from '../lib/state'
import { formatOffset, formatTime } from '../lib/format'
import type { Incident, TimelineStep, TimelineStepStatus } from '../types/events'
import { Panel, Pill, TONE, type Tone } from './Panel'

const STATUS_UI: Record<TimelineStepStatus, { text: string; tone: Tone; fill: string }> = {
  pending: { text: 'En attente', tone: 'mute', fill: '0%' },
  active: { text: 'En cours', tone: 'warn', fill: '50%' },
  done: { text: 'Terminé', tone: 'ok', fill: '100%' },
  failed: { text: 'Échec', tone: 'ko', fill: '100%' },
}

const IDLE: TimelineStep[] = [
  { id: 'detection', label: 'Détection', detail: 'Le détecteur ML surveille le score.' },
  { id: 'decision', label: 'Décision', detail: "Choix du playbook selon le type d'incident." },
  { id: 'action', label: 'Action', detail: 'Exécution automatique des actions.' },
  { id: 'verification', label: 'Vérification', detail: 'Transaction de paiement de contrôle.' },
].map((s) => ({ ...s, status: 'pending', ts: null, offsetSeconds: null }) as TimelineStep)

export function IncidentTimeline({ incident, now }: { incident: Incident | null; now?: number }) {
  const steps = incident ? buildTimeline(incident) : IDLE
  const liveOffset = incident && now !== undefined ? Math.max(0, (now - Date.parse(incident.detectedAt)) / 1000) : null

  return (
    <Panel
      title="Timeline d'incident"
      subtitle={
        <span className="font-mono">
          {incident ? `${incident.id} · ${INCIDENT_LABEL[incident.incidentType]} · ${incident.service}` : 'Aucun incident — la plateforme fonctionne normalement.'}
        </span>
      }
      aside={incident?.decision?.dryRun && <Pill tone="info">dry-run</Pill>}
    >
      <ol aria-label="Étapes de la remédiation" className="grid grid-cols-[repeat(auto-fit,minmax(150px,1fr))] gap-2.5">
        {steps.map((s, idx) => {
          const ui = STATUS_UI[s.status]
          const t = TONE[ui.tone]
          const elapsed = s.offsetSeconds !== null ? formatOffset(s.offsetSeconds) : s.status === 'active' && liveOffset !== null ? `${formatOffset(liveOffset)}…` : ''
          return (
            <li
              key={s.id}
              data-step={s.id}
              data-status={s.status}
              className={`flex min-w-0 flex-col gap-2.5 rounded-xl border bg-card-2 p-3.5 ${s.status === 'active' || s.status === 'failed' ? t.border : 'border-edge'}`}
            >
              <div className="flex items-center justify-between gap-1.5">
                <span className={`grid h-6 w-6 place-items-center rounded-full font-mono text-xs ${s.status === 'pending' ? 'bg-edge-2 text-mute-3' : `${t.bg} ${t.text}`}`} aria-hidden>
                  {idx + 1}
                </span>
                <Pill tone={ui.tone} className="text-[11px]">{ui.text}</Pill>
              </div>
              <span className="text-[15px] font-medium">{s.label}</span>
              <span className="min-h-8 text-xs text-pretty text-mute-2">{s.detail}</span>
              <div className="h-[3px] overflow-hidden rounded-sm bg-edge" aria-hidden>
                <div className={`h-full transition-[width] duration-400 ${t.solid}`} style={{ width: ui.fill }} />
              </div>
              <div className="flex justify-between font-mono text-[11px]">
                <span className="text-mute-2">{formatTime(s.ts)}</span>
                <span className={s.status === 'active' ? 'text-warn' : 'text-mute'}>{elapsed}</span>
              </div>
            </li>
          )
        })}
      </ol>
    </Panel>
  )
}
