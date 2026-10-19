import { describe, expect, it, vi } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useRemediationStream } from './useRemediationStream'
import { CONTRACT_ANOMALY_EVENT, FakeEventSource, fakeFactory } from '../test/fixtures'

function setup() {
  const handlers = { onMessage: vi.fn(), onRejected: vi.fn(), onStatus: vi.fn() }
  const hook = renderHook(() => useRemediationStream('/remediation/stream', handlers, fakeFactory))
  return { handlers, es: FakeEventSource.last!, ...hook }
}

describe('useRemediationStream (SSE)', () => {
  it('ouvre GET <base>/stream et suit open / reconnecting / closed', () => {
    const { handlers, es } = setup()
    expect(es.url).toBe('/remediation/stream')
    expect(handlers.onStatus).toHaveBeenLastCalledWith('connecting')
    act(() => es.open())
    expect(handlers.onStatus).toHaveBeenLastCalledWith('open')
    act(() => es.error(false))
    expect(handlers.onStatus).toHaveBeenLastCalledWith('reconnecting')
    act(() => es.error(true))
    expect(handlers.onStatus).toHaveBeenLastCalledWith('closed')
  })

  it('transmet les messages valides et compte les rejets', () => {
    const { handlers, es } = setup()
    act(() => es.emit('anomaly_detected', { ...CONTRACT_ANOMALY_EVENT, incident_id: 'i1' }))
    expect(handlers.onMessage).toHaveBeenCalledWith(expect.objectContaining({ kind: 'anomaly_detected', incidentId: 'i1' }))
    act(() => es.emit('anomaly_detected', { ...CONTRACT_ANOMALY_EVENT, incident_type: 'bogus' }))
    act(() => es.emit('score', '{pas json'))
    expect(handlers.onMessage).toHaveBeenCalledTimes(1)
    expect(handlers.onRejected).toHaveBeenCalledTimes(2)
  })

  it('accepte les événements sans nom (message) portant le type dans le corps', () => {
    const { handlers, es } = setup()
    act(() => es.emit('message', { type: 'verify_tx', ok: true }))
    expect(handlers.onMessage).toHaveBeenCalledWith(expect.objectContaining({ kind: 'verify_tx' }))
  })

  it('ferme la connexion au démontage', () => {
    const { es, unmount } = setup()
    unmount()
    expect(es.closed).toBe(true)
  })
})
