import { afterEach, describe, expect, it, vi } from 'vitest'
import { createServiceStatus } from './serviceStatus'

afterEach(() => vi.useRealTimers())

describe('état du service (bandeau D6)', () => {
  it('ok → perturbé sur échec → rétabli à la première réponse saine → masqué', () => {
    vi.useFakeTimers()
    const s = createServiceStatus(4000)
    const seen: string[] = []
    s.subscribe(() => seen.push(s.get()))
    s.report(true)
    expect(s.get()).toBe('ok')
    s.report(false)
    s.report(false)
    expect(s.get()).toBe('degraded')
    s.report(true)
    expect(s.get()).toBe('restored')
    vi.advanceTimersByTime(4000)
    expect(s.get()).toBe('ok')
    expect(seen).toEqual(['degraded', 'restored', 'ok'])
  })

  it('ignore une réponse saine d’une requête partie avant la panne (requêtes parallèles)', () => {
    let t = 0
    const s = createServiceStatus(4000, () => t)
    t = 10
    s.report(false) // échec détecté à t=10
    s.report(true, 5) // requête partie à t=5 : ne prouve pas la reprise
    expect(s.get()).toBe('degraded')
    s.report(true, 12)
    expect(s.get()).toBe('restored')
  })

  it('un nouvel échec pendant « rétabli » repasse en perturbé', () => {
    vi.useFakeTimers()
    const s = createServiceStatus(4000)
    s.report(false)
    s.report(true)
    s.report(false)
    vi.advanceTimersByTime(5000)
    expect(s.get()).toBe('degraded')
  })
})
