/** Démo de bout en bout contre l'enveloppe RÉELLE du moteur (`event: timeline`) + score/santé Prometheus. */
import { afterEach, describe, expect, it, vi } from 'vitest'
import { act, render, screen } from '@testing-library/react'
import { App } from './App'
import { ENGINE_TIMELINE, ENGINE_TIMELINE_ESCALATED, FakeEventSource, fakeFactory, PROM_SCORE, PROM_UP } from './test/fixtures'

const active = () => screen.getByRole('listitem', { current: 'step', name: undefined })

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

describe('Dashboard contre le moteur réel (event: timeline)', () => {
  it('service_flood : AVANT -> PENDANT -> APRÈS, timeline, actions et MTTR issus des trames du moteur', () => {
    render(<App streamUrl="/remediation/stream" eventSourceFactory={fakeFactory} source="live" liveTriggers={false} metricsBase={null} />)
    const es = FakeEventSource.last!
    act(() => es.open())
    expect(active()).toHaveTextContent('AVANT')

    const [detect, ...rest] = ENGINE_TIMELINE
    act(() => es.emit(detect![0], detect![1]))
    expect(active()).toHaveTextContent('PENDANT')
    expect(screen.getByTestId('score-gauge')).toHaveAttribute('data-level', 'alert')

    // décision, waf_block_ip OK, verify_tx KO : toujours PENDANT, vérification en échec visible
    for (const [name, data] of rest.slice(0, 4)) act(() => es.emit(name, data))
    expect(active()).toHaveTextContent('PENDANT')
    expect(screen.getByTestId('verification')).toHaveAttribute('data-ok', 'false')

    // restart_service OK, verify_tx OK, clôture (MTTD/MTTR) : APRÈS
    for (const [name, data] of rest.slice(4)) act(() => es.emit(name, data))
    expect(active()).toHaveTextContent('APRÈS')
    expect(screen.getByText('Reprise sans intervention humaine')).toBeInTheDocument()
    expect(screen.getByTestId('metric-mttr')).toHaveTextContent('9,0 s')
    expect(screen.getByTestId('metric-mttd')).toHaveTextContent('4,2 s')
    expect(screen.getByTestId('verification')).toHaveAttribute('data-ok', 'true')
    expect(screen.queryByText(/message(s)? rejeté/)).not.toBeInTheDocument()
  })

  it('data_corruption escaladé : reste PENDANT avec la raison d’escalade', () => {
    render(<App streamUrl="/remediation/stream" eventSourceFactory={fakeFactory} source="live" liveTriggers={false} metricsBase={null} />)
    const es = FakeEventSource.last!
    act(() => es.open())
    for (const [name, data] of ENGINE_TIMELINE_ESCALATED) act(() => es.emit(name, data))
    expect(active()).toHaveTextContent('PENDANT')
    expect(screen.getByText(/Échec \/ escalade/)).toBeInTheDocument()
  })

  it('score et santé viennent de Prometheus (proxy same-origin), pas du flux SSE', async () => {
    const fetchMock = vi.fn(async (url: string) => ({
      ok: true,
      json: async () => (url.includes('resilience_anomaly_score') ? PROM_SCORE : PROM_UP),
    }))
    vi.stubGlobal('fetch', fetchMock)
    render(<App streamUrl="/remediation/stream" eventSourceFactory={fakeFactory} source="live" liveTriggers={false} metricsBase="/prometheus" />)
    act(() => FakeEventSource.last!.open())
    await act(async () => {
      await Promise.resolve()
      await Promise.resolve()
    })
    expect(fetchMock.mock.calls.map(([u]) => u)).toEqual(
      expect.arrayContaining(['/prometheus/api/v1/query?query=resilience_anomaly_score', '/prometheus/api/v1/query?query=up']),
    )
    // Same-origin uniquement : proxy Prometheus + liste noire du WAF en lecture seule (carte « IP bloquées »).
    // Jamais remediation:8005 ni prometheus:9090 en direct.
    expect(
      fetchMock.mock.calls.every(([u]) => (u as string).startsWith('/prometheus/') || u === '/remediation/waf/blocked-ips'),
    ).toBe(true)
    expect(screen.getByTestId('score-gauge')).toHaveAttribute('data-level', 'alert') // payment-api 0.83 >= 0.6
    expect(screen.getByText('Hors service')).toBeInTheDocument() // up{job="payment-api"} = 0
    expect(active()).toHaveTextContent('AVANT') // un score haut sans incident moteur ne change pas la phase
  })
})
