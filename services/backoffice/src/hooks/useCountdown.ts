import { useCallback, useEffect, useRef, useState } from 'react'

/** Pas de rafraîchissement : assez fin pour un affichage à la seconde sans dérive visible. */
export const COUNTDOWN_TICK_MS = 250

export interface Countdown {
  /** Secondes restantes (arrondi supérieur) ; 0 = inactif. */
  left: number
  /** (Re)démarre pour `seconds` secondes ; `onDone` est appelé une fois à l'échéance. */
  start: (seconds: number, onDone?: () => void) => void
  /** Arrête sans appeler `onDone`. */
  cancel: () => void
}

// Décompte basé sur une échéance absolue (Date.now) : un onglet en arrière-plan qui ralentit
// les timers ne fausse pas la durée. Un seul décompte actif à la fois par instance.
export function useCountdown(): Countdown {
  const [left, setLeft] = useState(0)
  const deadlineRef = useRef(0)
  const onDoneRef = useRef<(() => void) | undefined>(undefined)

  const start = useCallback((seconds: number, onDone?: () => void) => {
    const s = Math.max(0, Math.ceil(seconds))
    deadlineRef.current = Date.now() + s * 1000
    onDoneRef.current = onDone
    setLeft(s)
    if (s === 0) onDone?.()
  }, [])

  const cancel = useCallback(() => {
    deadlineRef.current = 0
    onDoneRef.current = undefined
    setLeft(0)
  }, [])

  const active = left > 0
  useEffect(() => {
    if (!active) return
    const id = setInterval(() => {
      const rem = Math.max(0, Math.ceil((deadlineRef.current - Date.now()) / 1000))
      setLeft(rem)
      if (rem === 0) {
        const done = onDoneRef.current
        onDoneRef.current = undefined
        done?.()
      }
    }, COUNTDOWN_TICK_MS)
    return () => clearInterval(id)
  }, [active])

  return { left, start, cancel }
}

/** « 4:05 » pour l'écran de blocage. */
export function formatMinSec(seconds: number): string {
  const s = Math.max(0, Math.ceil(seconds))
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
}
