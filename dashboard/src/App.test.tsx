import { afterEach, describe, expect, it, vi } from 'vitest'
import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { App } from './App'
import type { StreamSource } from './config'
import { FULL_SEQUENCE, FakeEventSource, fakeFactory } from './test/fixtures'

function renderApp(opts: { source?: StreamSource; liveTriggers?: boolean } = {}) {
  render(<App streamUrl="/remediation/stream" eventSourceFactory={fakeFactory} source={opts.source ?? 'live'} liveTriggers={opts.liveTriggers ?? false} />)
  return FakeEventSource.last!
}
const active = () => screen.getByRole('listitem', { current: 'step', name: undefined })

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

describe('Dashboard - démo AVANT / PENDANT / APRÈS de bout en bout (SSE simulé)', () => {
  it('démarre en AVANT avec flux connecté, sans incident', () => {
    const es = renderApp()
    expect(es.url).toBe('/remediation/stream')
    expect(screen.getByTestId('connection')).toHaveAttribute('data-status', 'connecting')
    act(() => es.open())
    expect(screen.getByTestId('connection')).toHaveAttribute('data-status', 'open')
    expect(active()).toHaveTextContent('AVANT')
    expect(screen.getByText(/fonctionne normalement/)).toBeInTheDocument()
  })

  it('rejoue un incident service_flood : AVANT -> PENDANT -> APRÈS', () => {
    const es = renderApp()
    act(() => es.open())
    act(() => {
      es.emit('health', { services: [{ name: 'payment-api', status: 'up' }] })
      es.emit('score', { anomaly_score: 0.1, threshold: 0.6 })
      es.emit('verify_tx', { ok: true, tx_id: 'tx-pre' })
    })
    expect(active()).toHaveTextContent('AVANT')
    expect(screen.getByText('tx-pre')).toBeInTheDocument()

    const [detect, ...rest] = FULL_SEQUENCE
    act(() => es.emit(detect![0], detect![1]))
    expect(active()).toHaveTextContent('PENDANT')
    expect(screen.getByTestId('score-gauge')).toHaveAttribute('data-level', 'alert')

    act(() => es.emit('health', { services: [{ name: 'payment-api', status: 'down' }] }))
    expect(screen.getByText('Hors service')).toBeInTheDocument()

    for (const [name, data] of rest.slice(0, -1)) act(() => es.emit(name, data))
    expect(active()).toHaveTextContent('PENDANT')

    const [lastName, lastData] = rest.at(-1)!
    act(() => es.emit(lastName, lastData))
    expect(active()).toHaveTextContent('APRÈS')
    expect(screen.getByText('Reprise sans intervention humaine')).toBeInTheDocument()
    expect(screen.getByTestId('metric-mttr')).toHaveTextContent('9,0 s')
    expect(screen.getByTestId('metric-mttd')).toHaveTextContent('4,2 s')
    expect(screen.getByTestId('verification')).toHaveAttribute('data-ok', 'true')
    expect(screen.getByText('tx-verify-42')).toBeInTheDocument()
  })

  it('signale les messages non conformes au contrat sans casser la vue', () => {
    const es = renderApp()
    act(() => es.emit('anomaly_detected', { schema_version: '1.0', incident_type: 'zzz' }))
    expect(screen.getByText('1 message rejeté')).toBeInTheDocument()
    expect(active()).toHaveTextContent('AVANT')
  })

  it('« Réinitialiser la vue » ramène à AVANT', async () => {
    const es = renderApp()
    act(() => FULL_SEQUENCE.forEach(([n, d]) => es.emit(n, d)))
    expect(active()).toHaveTextContent('APRÈS')
    await userEvent.click(screen.getByRole('button', { name: 'Réinitialiser la vue' }))
    expect(active()).toHaveTextContent('AVANT')
  })

  it('affiche flux interrompu quand la connexion est fermée (mode live : pas de bascule)', () => {
    const es = renderApp()
    act(() => es.error(true))
    expect(screen.getByText('Flux interrompu')).toBeInTheDocument()
    expect(screen.queryByText(/simulation locale active/)).not.toBeInTheDocument()
  })

  it('liens Grafana présents ; déclencheurs masqués en flux réel hors dev', () => {
    renderApp()
    expect(screen.getByRole('navigation', { name: 'Liens Grafana' })).toBeInTheDocument()
    expect(screen.queryByText('Répétition · déclencher')).not.toBeInTheDocument()
  })
})

describe('Sources : simulation locale et déclencheurs', () => {
  it('mode simulation : flux local signalé, incident complet jusqu’à APRÈS sans serveur', async () => {
    vi.useFakeTimers()
    render(<App source="simulation" liveTriggers={false} />)
    await act(async () => vi.advanceTimersByTimeAsync(10))
    expect(screen.getByTestId('connection')).toHaveAttribute('data-status', 'open')
    expect(screen.getByText('simulation://local')).toBeInTheDocument()
    expect(screen.getByText(/Simulation locale/)).toBeInTheDocument()
    expect(active()).toHaveTextContent('AVANT')

    act(() => screen.getByRole('button', { name: /Corruption de données/ }).click())
    await act(async () => vi.advanceTimersByTimeAsync(3_000))
    expect(active()).toHaveTextContent('PENDANT')
    expect(screen.getByTestId('headline')).toHaveTextContent('postgres')
    await act(async () => vi.advanceTimersByTimeAsync(6_000))
    expect(active()).toHaveTextContent('APRÈS')
    // Corruption => restauration, jamais un redémarrage (disponibilité ≠ intégrité).
    const actions = [...document.querySelectorAll('[data-action]')].map((el) => [el.getAttribute('data-action'), el.getAttribute('data-result')])
    expect(actions).toEqual([['restore_pg_dump', 'ok']])
  })

  it('mode auto : bascule en simulation si le flux réel ne s’ouvre jamais', () => {
    const es = renderApp({ source: 'auto' })
    act(() => es.error(false))
    expect(screen.getByText(/Flux injoignable — simulation locale active/)).toBeInTheDocument()
    expect(es.closed).toBe(true)
  })

  it('mode auto : pas de bascule si le flux a été ouvert puis coupé', () => {
    const es = renderApp({ source: 'auto' })
    act(() => es.open())
    act(() => es.error(false))
    expect(screen.getByTestId('connection')).toHaveAttribute('data-status', 'reconnecting')
    expect(screen.queryByText(/simulation locale active/)).not.toBeInTheDocument()
  })

  it('bascule manuelle réel <-> simulation', async () => {
    const es = renderApp()
    await userEvent.click(screen.getByRole('button', { name: 'Passer en simulation' }))
    expect(es.closed).toBe(true)
    expect(screen.getByText('simulation://local')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Réessayer le flux réel' }))
    expect(FakeEventSource.last).not.toBe(es)
    expect(screen.getByText('/remediation/stream')).toBeInTheDocument()
  })

  it('déclencheur en flux réel (dev / mock) : GET <base>/trigger?type=…', async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ started: true }), { status: 202 }))
    vi.stubGlobal('fetch', fetchMock)
    renderApp({ liveTriggers: true })
    await userEvent.click(screen.getByRole('button', { name: /Abus d'authentification/ }))
    expect(fetchMock).toHaveBeenCalledWith('/remediation/trigger?type=auth_abuse')
    expect(await screen.findByText('Incident auth_abuse démarré')).toBeInTheDocument()
  })
})
