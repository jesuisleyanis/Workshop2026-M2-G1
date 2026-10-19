import { formatDuration } from '../lib/format'
import { INCIDENT_LABEL, incidentMttr } from '../lib/state'
import type { Incident, Phase } from '../types/events'
import { Pill, TONE, type Tone } from './Panel'

interface Props {
  phase: Phase
  incident: Incident | null
}

const STEPS: { phase: Phase; label: string }[] = [
  { phase: 'before', label: 'AVANT' },
  { phase: 'during', label: 'PENDANT' },
  { phase: 'after', label: 'APRÈS' },
]

function caption(p: Phase, incident: Incident | null): string {
  if (p === 'before') return 'Système nominal'
  if (p === 'after') return 'Service rétabli · vérification OK'
  return incident?.failure ? 'Échec · escalade opérateur' : 'Remédiation automatique en cours'
}

function tone(p: Phase, incident: Incident | null): Tone {
  if (p === 'during') return incident?.failure ? 'ko' : 'warn'
  return 'ok'
}

export function headline(p: Phase, i: Incident | null): string {
  if (p === 'before' || !i) return 'Surveillance active · aucun incident en cours'
  if (p === 'after') return `Service ${i.service} rétabli en ${formatDuration(incidentMttr(i))} · transaction de vérification OK`
  if (i.failure) return `Remédiation échouée sur ${i.service} : ${i.failure.reason}`
  return `${INCIDENT_LABEL[i.incidentType]} détecté sur ${i.service} · remédiation automatique en cours`
}

/** Exigence R20 : l'état avant / pendant / après l'incident est toujours lisible. */
export function PhaseBanner({ phase, incident }: Props) {
  return (
    <section aria-label="Phase de la démonstration" className="flex flex-col gap-3 rounded-2xl border border-edge bg-[#131315] p-4">
      <ol className="grid grid-cols-1 gap-2 sm:grid-cols-3">
        {STEPS.map((s) => {
          const isActive = s.phase === phase
          const t = TONE[tone(s.phase, incident)]
          return (
            <li
              key={s.phase}
              data-phase={s.phase}
              data-active={isActive}
              aria-current={isActive ? 'step' : undefined}
              className={`flex items-center gap-3 rounded-[11px] border px-3.5 py-3 transition-all duration-300 ${isActive ? `${t.bg} ${t.border}` : 'border-edge'}`}
            >
              <span className={`h-[9px] w-[9px] flex-none rounded-full ${isActive ? t.solid : 'bg-[#3f3f46]'}`} aria-hidden />
              <div className="flex min-w-0 flex-col gap-0.5">
                <span className={`text-[13px] font-semibold tracking-[0.08em] ${isActive ? t.text : 'text-mute-3'}`}>{s.label}</span>
                <span className={`text-xs ${isActive ? 'text-fg-2' : 'text-mute-4'}`}>{caption(s.phase, incident)}</span>
              </div>
            </li>
          )
        })}
      </ol>
      <div className="flex flex-wrap items-center justify-between gap-3 px-1">
        <span className="text-[15px] text-pretty text-fg-2" data-testid="headline">{headline(phase, incident)}</span>
        {phase === 'after' && <Pill tone="ok">Reprise sans intervention humaine</Pill>}
      </div>
    </section>
  )
}
