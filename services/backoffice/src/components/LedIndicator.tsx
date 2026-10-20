import { ledView, type LedState } from '../lib/led'

// Reflet UI de la LED physique (contrat §5.3). `data-led` facilite les assertions de test.
export function LedIndicator({ state }: { state: LedState }) {
  const view = ledView(state)
  const color =
    view.color === 'green' ? 'var(--color-led-green)' : view.color === 'red' ? 'var(--color-led-red)' : '#cbd0d6'
  return (
    <div className="flex items-center gap-3" data-testid="led" data-led={state}>
      <span
        aria-hidden
        className={view.blink ? 'animate-pulse' : ''}
        style={{
          width: 14,
          height: 14,
          borderRadius: '9999px',
          background: color,
          boxShadow: view.color === 'off' ? 'none' : `0 0 10px ${color}`,
        }}
      />
      <span className="text-sm text-ink-2">{view.label}</span>
    </div>
  )
}
