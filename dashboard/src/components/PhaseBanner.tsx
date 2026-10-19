import type { Incident, Phase } from '../types/events'

interface Props {
  phase: Phase
  incident: Incident | null
}

const STEPS: { phase: Phase; label: string; active: string }[] = [
  { phase: 'before', label: 'AVANT', active: 'border-sky-400 bg-sky-500/20 text-sky-200' },
  { phase: 'during', label: 'PENDANT', active: 'border-red-400 bg-red-500/25 text-red-100 animate-pulse-ring' },
  { phase: 'after', label: 'APRÈS', active: 'border-emerald-400 bg-emerald-500/20 text-emerald-200' },
]

function caption(p: Phase, incident: Incident | null): string {
  if (p === 'before') return 'Système nominal'
  if (p === 'after') return 'Service rétabli - vérification OK'
  return incident?.failure ? 'Échec - escalade opérateur' : 'Incident - remédiation automatique en cours'
}

/** Exigence R20 : l'état avant / pendant / après l'incident est toujours lisible. */
export function PhaseBanner({ phase, incident }: Props) {
  return (
    <ol aria-label="Phase de la démonstration" className="grid grid-cols-3 gap-4">
      {STEPS.map((s) => {
        const isActive = s.phase === phase
        return (
          <li
            key={s.phase}
            data-phase={s.phase}
            data-active={isActive}
            aria-current={isActive ? 'step' : undefined}
            className={`rounded-2xl border-2 px-6 py-5 text-center transition-all duration-300 ${
              isActive ? `${s.active} scale-[1.02]` : 'border-slate-800 bg-slate-900/40 text-slate-600'
            }`}
          >
            <p className="text-4xl font-black tracking-widest xl:text-5xl">{s.label}</p>
            <p className={`mt-1 min-h-6 text-lg font-medium ${isActive ? '' : 'invisible'}`}>{isActive ? caption(s.phase, incident) : '.'}</p>
          </li>
        )
      })}
    </ol>
  )
}
