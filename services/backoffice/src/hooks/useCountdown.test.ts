import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, renderHook } from '@testing-library/react'
import { formatMinSec, useCountdown } from './useCountdown'

beforeEach(() => {
  vi.useFakeTimers()
})
afterEach(() => {
  vi.useRealTimers()
})

describe('useCountdown', () => {
  it('décompte à la seconde puis appelle onDone une seule fois', () => {
    const done = vi.fn()
    const { result } = renderHook(() => useCountdown())
    act(() => result.current.start(3, done))
    expect(result.current.left).toBe(3)
    act(() => vi.advanceTimersByTime(1_000))
    expect(result.current.left).toBe(2)
    act(() => vi.advanceTimersByTime(2_000))
    expect(result.current.left).toBe(0)
    act(() => vi.advanceTimersByTime(5_000))
    expect(done).toHaveBeenCalledTimes(1)
  })

  it('cancel arrête sans appeler onDone', () => {
    const done = vi.fn()
    const { result } = renderHook(() => useCountdown())
    act(() => result.current.start(5, done))
    act(() => result.current.cancel())
    act(() => vi.advanceTimersByTime(10_000))
    expect(result.current.left).toBe(0)
    expect(done).not.toHaveBeenCalled()
  })

  it('un nouveau start remplace le précédent (enchaînement refroidissement -> blocage)', () => {
    const second = vi.fn()
    const { result } = renderHook(() => useCountdown())
    act(() => result.current.start(2, () => result.current.start(4, second)))
    act(() => vi.advanceTimersByTime(2_000))
    expect(result.current.left).toBe(4)
    act(() => vi.advanceTimersByTime(4_000))
    expect(second).toHaveBeenCalledTimes(1)
  })
})

describe('formatMinSec', () => {
  it('m:ss', () => {
    expect(formatMinSec(300)).toBe('5:00')
    expect(formatMinSec(65)).toBe('1:05')
    expect(formatMinSec(0.2)).toBe('0:01')
  })
})
