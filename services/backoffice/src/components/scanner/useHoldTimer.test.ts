import { describe, expect, it } from 'vitest'
import { act, renderHook } from '@testing-library/react'
import { HOLD_INITIAL, holdStep, useHoldTimer } from './useHoldTimer'

// Horloge explicite (horodatages rAF) : aucun timer réel, tests déterministes.
function run(seq: Array<[boolean, number]>, holdMs = 300, graceMs = 150) {
  let s = HOLD_INITIAL
  for (const [active, now] of seq) s = holdStep(s, active, now, holdMs, graceMs)
  return s
}

describe('holdStep — maintien de pose', () => {
  it('accumule le temps uniquement entre trames actives consécutives', () => {
    const s = run([
      [true, 0],
      [true, 100],
      [true, 200],
    ])
    expect(s.elapsed).toBe(200)
    expect(s.complete).toBe(false)
  })

  it('se termine après holdMs de maintien continu', () => {
    const s = run([
      [true, 0],
      [true, 100],
      [true, 200],
      [true, 300],
    ])
    expect(s.complete).toBe(true)
  })

  it('gèle la progression pendant une courte perte (tolérance), puis reprend', () => {
    const s = run([
      [true, 0],
      [true, 100],
      [false, 150], // perte < tolérance : on garde 100
      [true, 200], // reprise : la trame de reprise ne compte pas l'intervalle perdu
      [true, 250],
    ])
    expect(s.elapsed).toBe(150)
  })

  it('remet à zéro si la pose est perdue au-delà de la tolérance', () => {
    const s = run([
      [true, 0],
      [true, 200],
      [false, 250],
      [false, 450],
    ])
    expect(s.elapsed).toBe(0)
    expect(s.complete).toBe(false)
  })

  it('borne un saut de temps (onglet masqué) pour ne pas valider d’un coup', () => {
    const s = run([
      [true, 0],
      [true, 5000],
    ])
    expect(s.elapsed).toBeLessThan(300)
    expect(s.complete).toBe(false)
  })
})

describe('useHoldTimer', () => {
  it('expose une progression 0..1 et se réinitialise', () => {
    const { result } = renderHook(() => useHoldTimer(400))
    expect(result.current.progress).toBe(0)
    let done = false
    act(() => {
      done = result.current.tick(true, 0)
      done = result.current.tick(true, 100)
      done = result.current.tick(true, 200)
    })
    expect(done).toBe(false)
    expect(result.current.progress).toBeCloseTo(0.5)
    act(() => {
      result.current.tick(true, 300)
      done = result.current.tick(true, 400)
    })
    expect(done).toBe(true)
    expect(result.current.progress).toBe(1)
    act(() => result.current.reset())
    expect(result.current.progress).toBe(0)
  })
})
