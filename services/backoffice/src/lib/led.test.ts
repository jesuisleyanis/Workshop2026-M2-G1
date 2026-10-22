import { describe, expect, it } from 'vitest'
import { LED_TIMINGS, ledActive, ledLabel, ledOutputAt, msUntilLedChange } from './led'

// Miroir de iot/esp8266-led/lib/led/led_controller.h : mêmes timings, même découpage.
describe('ledOutputAt (jumeau du firmware, contrat §5.3)', () => {
  it('reprend les timings du firmware', () => {
    expect(LED_TIMINGS).toEqual({
      greenBlinkHalf: 400,
      redBlinkHalf: 150,
      redBlinkCount: 10,
      greenSolidMs: 30_000,
      redSolidMs: 30_000,
    })
  })

  it('idle : éteinte en permanence', () => {
    expect(ledOutputAt('idle', 0)).toEqual({ color: 'off', on: false })
    expect(ledOutputAt('idle', 120_000)).toEqual({ color: 'off', on: false })
  })

  it('recognized : vert clignotant (demi-période 400 ms) sans fin', () => {
    expect(ledOutputAt('recognized', 0)).toEqual({ color: 'green', on: true })
    expect(ledOutputAt('recognized', 399)).toEqual({ color: 'green', on: true })
    expect(ledOutputAt('recognized', 400)).toEqual({ color: 'green', on: false })
    expect(ledOutputAt('recognized', 799)).toEqual({ color: 'green', on: false })
    expect(ledOutputAt('recognized', 800)).toEqual({ color: 'green', on: true })
    // Toujours en cours bien après 30 s : seul l'état suivant l'arrête.
    expect(ledOutputAt('recognized', 60_000).color).toBe('green')
  })

  it('auth_ok : vert fixe 30 s puis éteinte', () => {
    expect(ledOutputAt('auth_ok', 0)).toEqual({ color: 'green', on: true })
    expect(ledOutputAt('auth_ok', 29_999)).toEqual({ color: 'green', on: true })
    expect(ledOutputAt('auth_ok', 30_000)).toEqual({ color: 'off', on: false })
  })

  it('auth_fail : rouge ×10 (demi-période 150 ms) = 3000 ms puis éteinte', () => {
    expect(ledOutputAt('auth_fail', 0)).toEqual({ color: 'red', on: true })
    expect(ledOutputAt('auth_fail', 149)).toEqual({ color: 'red', on: true })
    expect(ledOutputAt('auth_fail', 150)).toEqual({ color: 'red', on: false })
    // 10 allumages : début de chaque période de 300 ms.
    const flashes = Array.from({ length: 3000 }, (_, t) => t).filter(
      (t) => ledOutputAt('auth_fail', t).on && (t === 0 || !ledOutputAt('auth_fail', t - 1).on),
    )
    expect(flashes).toHaveLength(10)
    expect(ledOutputAt('auth_fail', 2_999)).toEqual({ color: 'red', on: false })
    expect(ledOutputAt('auth_fail', 3_000)).toEqual({ color: 'off', on: false })
  })

  it('not_recognized : rouge fixe 30 s puis éteinte', () => {
    expect(ledOutputAt('not_recognized', 0)).toEqual({ color: 'red', on: true })
    expect(ledOutputAt('not_recognized', 29_999)).toEqual({ color: 'red', on: true })
    expect(ledOutputAt('not_recognized', 30_000)).toEqual({ color: 'off', on: false })
  })

  it('un écart négatif (horloge en retard) vaut 0', () => {
    expect(ledOutputAt('auth_fail', -50)).toEqual({ color: 'red', on: true })
  })
})

describe('msUntilLedChange', () => {
  it('prochaine bascule de clignotement ou fin de séquence', () => {
    expect(msUntilLedChange('idle', 0)).toBeNull()
    expect(msUntilLedChange('recognized', 0)).toBe(400)
    expect(msUntilLedChange('recognized', 650)).toBe(150)
    expect(msUntilLedChange('auth_fail', 100)).toBe(50)
    expect(msUntilLedChange('auth_fail', 3_000)).toBeNull()
    expect(msUntilLedChange('auth_ok', 10_000)).toBe(20_000)
    expect(msUntilLedChange('not_recognized', 30_000)).toBeNull()
  })
})

describe('ledActive / ledLabel', () => {
  it('séquence terminée = éteinte', () => {
    expect(ledActive('not_recognized', 1_000)).toBe(true)
    expect(ledActive('not_recognized', 30_000)).toBe(false)
    expect(ledActive('recognized', 120_000)).toBe(true)
    expect(ledActive('idle', 0)).toBe(false)
  })
  it('libellés en français', () => {
    expect(ledLabel('idle', 0)).toBe('Éteinte')
    expect(ledLabel('recognized', 0)).toMatch(/vert clignotant/i)
    expect(ledLabel('auth_ok', 0)).toMatch(/vert fixe/i)
    expect(ledLabel('auth_fail', 0)).toMatch(/rouge clignotant/i)
    expect(ledLabel('not_recognized', 0)).toMatch(/rouge fixe/i)
    expect(ledLabel('auth_fail', 3_000)).toBe('Éteinte')
  })
})
