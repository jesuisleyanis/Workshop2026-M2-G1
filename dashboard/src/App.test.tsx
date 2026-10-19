import { describe, expect, it } from 'vitest'
import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { App } from './App'
import { FULL_SEQUENCE, FakeEventSource, fakeFactory } from './test/fixtures'

function renderApp() {
  render(<App streamUrl="/remediation/stream" eventSourceFactory={fakeFactory} />)
  return FakeEventSource.last!
}
const active = () => screen.getByRole('listitem', { current: 'step', name: undefined })

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
    expect(screen.getByText('HORS SERVICE')).toBeInTheDocument()

    for (const [name, data] of rest.slice(0, -1)) act(() => es.emit(name, data))
    expect(active()).toHaveTextContent('PENDANT')

    const [lastName, lastData] = rest.at(-1)!
    act(() => es.emit(lastName, lastData))
    expect(active()).toHaveTextContent('APRÈS')
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

  it('affiche flux interrompu quand la connexion est fermée', () => {
    const es = renderApp()
    act(() => es.error(true))
    expect(screen.getByText('Flux interrompu')).toBeInTheDocument()
  })

  it('liens Grafana présents', () => {
    renderApp()
    expect(screen.getByRole('navigation', { name: 'Liens Grafana' })).toBeInTheDocument()
  })
})
