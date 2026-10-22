// Jumeau UI de la LED physique (contrat §5.3). La vraie LED est pilotée par `auth` via MQTT ;
// le back-office en affiche un reflet pour l'opérateur, avec EXACTEMENT les timings du firmware
// (iot/esp8266-led/lib/led/led_controller.h) : toute évolution là-bas doit être reportée ici.
import { useEffect, useState } from 'react'

export type LedState = 'idle' | 'recognized' | 'auth_ok' | 'auth_fail' | 'not_recognized'
export type LedColor = 'off' | 'green' | 'red'

export interface LedOutput {
  color: LedColor
  /** Allumée à cet instant (gère le clignotement). */
  on: boolean
}

/** Miroir de `LedTimings` (firmware). */
export const LED_TIMINGS = {
  greenBlinkHalf: 400, // vert clignotant : demi-période
  redBlinkHalf: 150, // rouge clignotant : demi-période
  redBlinkCount: 10, // rouge clignote 10 fois puis s'éteint
  greenSolidMs: 30_000, // vert fixe 30 s puis s'éteint
  redSolidMs: 30_000, // rouge fixe 30 s puis s'éteint
} as const

const RED_BLINK_TOTAL = LED_TIMINGS.redBlinkHalf * 2 * LED_TIMINGS.redBlinkCount // 3000 ms

/** Durée de la séquence avant extinction ; `null` = jusqu'à l'état suivant. */
const DURATION: Record<LedState, number | null> = {
  idle: 0,
  recognized: null,
  auth_ok: LED_TIMINGS.greenSolidMs,
  auth_fail: RED_BLINK_TOTAL,
  not_recognized: LED_TIMINGS.redSolidMs,
}

const OFF: LedOutput = { color: 'off', on: false }

// Allumée pendant la première moitié de chaque période, éteinte pendant la seconde.
const blinkOn = (elapsed: number, half: number) => Math.floor(elapsed / half) % 2 === 0

/** La séquence de `state` est-elle encore en cours après `elapsedMs` ? */
export function ledActive(state: LedState, elapsedMs: number): boolean {
  const d = DURATION[state]
  return d === null || Math.max(0, elapsedMs) < d
}

/** Sortie de la LED `elapsedMs` après l'entrée dans `state` (fonction pure, cf. firmware update()). */
export function ledOutputAt(state: LedState, elapsedMs: number): LedOutput {
  const t = Math.max(0, elapsedMs)
  if (!ledActive(state, t)) return OFF
  switch (state) {
    case 'recognized':
      return { color: 'green', on: blinkOn(t, LED_TIMINGS.greenBlinkHalf) }
    case 'auth_ok':
      return { color: 'green', on: true }
    case 'auth_fail':
      return { color: 'red', on: blinkOn(t, LED_TIMINGS.redBlinkHalf) }
    case 'not_recognized':
      return { color: 'red', on: true }
    default:
      return OFF
  }
}

/** Délai avant le prochain changement de sortie ; `null` si plus rien ne changera. */
export function msUntilLedChange(state: LedState, elapsedMs: number): number | null {
  const t = Math.max(0, elapsedMs)
  if (!ledActive(state, t)) return null
  switch (state) {
    case 'recognized':
      return LED_TIMINGS.greenBlinkHalf - (t % LED_TIMINGS.greenBlinkHalf)
    case 'auth_fail':
      // 3000 ms est un multiple de la demi-période : la dernière bascule coïncide avec la fin.
      return LED_TIMINGS.redBlinkHalf - (t % LED_TIMINGS.redBlinkHalf)
    default:
      return (DURATION[state] as number) - t
  }
}

const LABELS: Record<LedState, string> = {
  idle: 'Éteinte',
  recognized: 'Vert clignotant — visage reconnu',
  auth_ok: 'Vert fixe — accès autorisé',
  auth_fail: 'Rouge clignotant — mot de passe refusé',
  not_recognized: 'Rouge fixe — visage non reconnu',
}

/** Libellé de la séquence en cours (« Éteinte » une fois terminée). */
export function ledLabel(state: LedState, elapsedMs: number): string {
  return ledActive(state, elapsedMs) ? LABELS[state] : LABELS.idle
}

export interface LedTimeline extends LedOutput {
  label: string
}

/**
 * Rejoue la séquence firmware de `state` depuis `startedAt` (horodatage `Date.now()`).
 * Un seul timer, programmé sur la prochaine bascule : pas de boucle à vide.
 */
export function useLedTimeline(state: LedState, startedAt: number): LedTimeline {
  const [now, setNow] = useState(() => Date.now())
  const elapsed = Math.max(0, now - startedAt)

  useEffect(() => {
    const wait = msUntilLedChange(state, elapsed)
    if (wait === null) return
    // Échéance absolue : rattrape un rendu tardif (horloge réelle en avance sur `now`).
    const due = startedAt + elapsed + wait
    const t = setTimeout(() => setNow(Date.now()), Math.max(0, due - Date.now()))
    return () => clearTimeout(t)
  }, [state, startedAt, elapsed])

  return { ...ledOutputAt(state, elapsed), label: ledLabel(state, elapsed) }
}
