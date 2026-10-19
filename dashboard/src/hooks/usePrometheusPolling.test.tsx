import { afterEach, describe, expect, it, vi } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { usePrometheusPolling, type FetchLike } from './usePrometheusPolling'
import { PROM_SCORE, PROM_UP } from '../test/fixtures'

const flush = () =>
  act(async () => {
    await Promise.resolve()
    await Promise.resolve()
    await Promise.resolve()
  })

afterEach(() => vi.useRealTimers())

describe('usePrometheusPolling', () => {
  it('interroge score + up immédiatement puis à chaque intervalle, et émet score/health', async () => {
    vi.useFakeTimers()
    const fetchImpl: FetchLike = vi.fn(async (url) => ({ ok: true, json: async () => (url.includes('anomaly') ? PROM_SCORE : PROM_UP) }))
    const onMessage = vi.fn()
    renderHook(() => usePrometheusPolling('/prometheus', onMessage, 1000, fetchImpl))
    await flush()
    expect(fetchImpl).toHaveBeenCalledTimes(2)
    expect(onMessage.mock.calls.map(([m]) => m.kind)).toEqual(['score', 'score', 'health'])

    await act(async () => {
      vi.advanceTimersByTime(1000)
    })
    await flush()
    expect(fetchImpl).toHaveBeenCalledTimes(4)
  })

  it('base vide/null : aucun appel ; erreurs réseau ou HTTP : ignorées, polling maintenu', async () => {
    vi.useFakeTimers()
    const onMessage = vi.fn()
    const fetchImpl: FetchLike = vi.fn(async () => {
      throw new Error('réseau')
    })
    renderHook(() => usePrometheusPolling(null, onMessage, 1000, fetchImpl))
    await flush()
    expect(fetchImpl).not.toHaveBeenCalled()

    const { unmount } = renderHook(() => usePrometheusPolling('/prometheus', onMessage, 1000, fetchImpl))
    await flush()
    expect(onMessage).not.toHaveBeenCalled()
    await act(async () => {
      vi.advanceTimersByTime(1000)
    })
    expect(fetchImpl).toHaveBeenCalledTimes(4)
    unmount()
    await act(async () => {
      vi.advanceTimersByTime(5000)
    })
    expect(fetchImpl).toHaveBeenCalledTimes(4) // arrêté au démontage
  })
})
