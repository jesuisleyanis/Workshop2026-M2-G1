import { useLedTimeline, type LedState } from '../lib/led'

const COLORS = { green: 'var(--color-led-green)', red: 'var(--color-led-red)' } as const

// Jumeau de la LED physique (contrat §5.3), posé sur le panneau nuit du login. Le clignotement
// est rejoué aux timings du firmware (lib/led.ts), pas par une animation CSS approximative.
// `data-*` facilitent les assertions de test.
export function LedIndicator({ state, startedAt }: { state: LedState; startedAt: number }) {
  const out = useLedTimeline(state, startedAt)
  const lit = out.color !== 'off' && out.on
  const color = out.color === 'off' ? undefined : COLORS[out.color]
  return (
    <div className="flex items-center gap-3.5" data-testid="led" data-led={state} data-color={out.color} data-on={out.on}>
      <span
        aria-hidden
        className="grid h-9 w-9 shrink-0 place-items-center rounded-full border border-[#33363d] bg-night"
      >
        <span
          className="h-3.5 w-3.5 rounded-full"
          style={{
            background: lit ? color : '#3a3d45',
            boxShadow: lit ? `0 0 12px ${color}` : 'none',
          }}
        />
      </span>
      <span className="flex flex-col gap-0.5">
        <span className="text-xs text-[#a7abb3]">Jumeau LED</span>
        <span className="text-sm font-medium text-[#f3f4f6]">{out.label}</span>
      </span>
    </div>
  )
}
