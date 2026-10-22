import { useCallback, useRef, useState } from 'react'

// Minuterie de maintien de pose, pilotée par les horodatages de la boucle rAF (pas de timer
// propre) : déterministe en test et synchronisée avec la détection.
//  - le temps ne s'accumule qu'entre deux trames actives consécutives ;
//  - une perte brève (< graceMs, ex. un landmark qui tremble au seuil) gèle la progression ;
//  - au-delà, la progression repart de zéro ;
//  - un saut de temps (onglet masqué) est borné à MAX_STEP_MS.

export const MAX_STEP_MS = 100
export const DEFAULT_GRACE_MS = 150

export interface HoldState {
  elapsed: number
  last: number | null
  prevActive: boolean
  inactiveSince: number | null
  complete: boolean
}

export const HOLD_INITIAL: HoldState = {
  elapsed: 0,
  last: null,
  prevActive: false,
  inactiveSince: null,
  complete: false,
}

export function holdStep(s: HoldState, active: boolean, now: number, holdMs: number, graceMs: number): HoldState {
  const dt = s.last === null ? 0 : Math.min(Math.max(now - s.last, 0), MAX_STEP_MS)
  let { elapsed, inactiveSince } = s
  if (active) {
    if (s.prevActive) elapsed += dt
    inactiveSince = null
  } else {
    inactiveSince ??= now
    if (now - inactiveSince >= graceMs) elapsed = 0
  }
  return { elapsed, last: now, prevActive: active, inactiveSince, complete: elapsed >= holdMs }
}

export interface HoldTimer {
  /** Progression 0..1 (quantifiée au centième pour limiter les rendus). */
  progress: number
  /** À appeler à chaque trame ; renvoie true quand le maintien est accompli. */
  tick: (active: boolean, now: number) => boolean
  reset: () => void
}

export function useHoldTimer(holdMs: number, graceMs = DEFAULT_GRACE_MS): HoldTimer {
  const [progress, setProgress] = useState(0)
  const state = useRef<HoldState>(HOLD_INITIAL)

  const tick = useCallback(
    (active: boolean, now: number) => {
      const next = holdStep(state.current, active, now, holdMs, graceMs)
      state.current = next
      setProgress(Math.round(Math.min(next.elapsed / holdMs, 1) * 100) / 100)
      return next.complete
    },
    [holdMs, graceMs],
  )

  const reset = useCallback(() => {
    state.current = HOLD_INITIAL
    setProgress(0)
  }, [])

  return { progress, tick, reset }
}
