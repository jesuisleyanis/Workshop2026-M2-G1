import { describe, expect, it } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import { GrafanaLinks, grafanaLinks } from './GrafanaLinks'
import { IncidentTimeline } from './IncidentTimeline'
import { MetricsCards } from './MetricsCards'
import { PhaseBanner } from './PhaseBanner'
import { ScoreGauge, gaugePoint } from './ScoreGauge'
import { ServicesGrid } from './ServicesGrid'
import { VerificationCard } from './VerificationCard'
import { derivePhase, initialState, latestIncident, reducer } from '../lib/state'
import { parseStreamMessage } from '../lib/parse'
import { FULL_SEQUENCE } from '../test/fixtures'
import type { DashboardState, Phase } from '../types/events'

function play(n: number): DashboardState {
  return FULL_SEQUENCE.slice(0, n).reduce((s, [name, data]) => {
    const r = parseStreamMessage(name, JSON.stringify(data))
    if (!r.ok) throw new Error(r.error)
    return reducer(s, { type: 'message', message: r.value })
  }, initialState)
}

describe('PhaseBanner - garde AVANT / PENDANT / APRÈS', () => {
  const cases: [Phase, string][] = [
    ['before', 'AVANT'],
    ['during', 'PENDANT'],
    ['after', 'APRÈS'],
  ]
  it.each(cases)('phase %s : seul « %s » est actif (aria-current)', (phase, label) => {
    render(<PhaseBanner phase={phase} incident={null} />)
    const items = screen.getAllByRole('listitem')
    expect(items.map((li) => li.getAttribute('data-phase'))).toEqual(['before', 'during', 'after'])
    const active = items.filter((li) => li.getAttribute('aria-current') === 'step')
    expect(active).toHaveLength(1)
    expect(active[0]).toHaveTextContent(label)
    expect(items.filter((li) => li.getAttribute('data-active') === 'true')).toHaveLength(1)
  })

  it('affiche les trois libellés en permanence', () => {
    render(<PhaseBanner phase="before" incident={null} />)
    for (const t of ['AVANT', 'PENDANT', 'APRÈS']) expect(screen.getByText(t)).toBeInTheDocument()
  })

  it.each([
    [0, 'before', 'Système nominal'],
    [2, 'during', 'remédiation automatique en cours'],
    [5, 'after', 'vérification OK'],
  ] as const)('à partir du flux (%i messages) : phase %s', (n, phase, caption) => {
    const s = play(n)
    expect(derivePhase(s)).toBe(phase)
    render(<PhaseBanner phase={derivePhase(s)} incident={latestIncident(s)} />)
    expect(screen.getByRole('listitem', { current: 'step' })).toHaveTextContent(caption)
  })

  it("escalade : PENDANT affiche l'échec", () => {
    const s = reducer(play(3), {
      type: 'message',
      message: { kind: 'remediation_failed', ts: '2026-10-21T09:15:00.000Z', incidentId: 'inc-001', reason: 'x' },
    })
    render(<PhaseBanner phase={derivePhase(s)} incident={latestIncident(s)} />)
    expect(screen.getByRole('listitem', { current: 'step' })).toHaveTextContent('escalade')
  })
})

describe('IncidentTimeline', () => {
  it('sans incident : message nominal', () => {
    render(<IncidentTimeline incident={null} />)
    expect(screen.getByText(/fonctionne normalement/)).toBeInTheDocument()
  })
  it('incident résolu : 4 étapes dans l’ordre, toutes terminées, signaux dominants', () => {
    render(<IncidentTimeline incident={latestIncident(play(5))} />)
    const steps = within(screen.getByRole('list', { name: 'Étapes de la remédiation' })).getAllByRole('listitem')
    expect(steps.map((s) => s.getAttribute('data-step'))).toEqual(['detection', 'decision', 'action', 'verification'])
    expect(steps.every((s) => s.getAttribute('data-status') === 'done')).toBe(true)
    expect(screen.getByText('Saturation du service')).toBeInTheDocument()
    expect(screen.getByText(/req_per_s z=9.2/)).toBeInTheDocument()
  })
  it('incident en cours : une seule étape active', () => {
    render(<IncidentTimeline incident={latestIncident(play(2))} />)
    const statuses = screen.getAllByRole('listitem').map((s) => s.getAttribute('data-status'))
    expect(statuses).toEqual(['done', 'done', 'active', 'pending'])
  })
})

describe('ScoreGauge', () => {
  it('sans donnée : en attente', () => {
    render(<ScoreGauge score={null} history={[]} />)
    expect(screen.getByText('EN ATTENTE')).toBeInTheDocument()
    expect(screen.getByTestId('score-gauge')).toHaveAttribute('data-level', 'none')
  })
  it('score au-dessus du seuil : ANOMALIE', () => {
    const s = play(1)
    render(<ScoreGauge score={s.score} history={s.history} />)
    expect(screen.getByTestId('score-value')).toHaveTextContent('0.87')
    expect(screen.getByText('ANOMALIE')).toBeInTheDocument()
    expect(screen.getByText(/seuil de détection : 0.60/)).toBeInTheDocument()
  })
  it('géométrie : 0 à gauche, 1 à droite, 0.5 en haut', () => {
    expect(gaugePoint(0).x).toBeCloseTo(20)
    expect(gaugePoint(0).y).toBeCloseTo(100)
    expect(gaugePoint(1).x).toBeCloseTo(180)
    expect(gaugePoint(0.5).y).toBeCloseTo(20)
  })
})

describe('MetricsCards', () => {
  it('MTTD/MTTR affichés pour un incident résolu', () => {
    render(<MetricsCards incident={latestIncident(play(5))} now={Date.parse('2026-10-21T09:20:00Z')} />)
    expect(screen.getByTestId('metric-mttd')).toHaveTextContent('4,2 s')
    expect(screen.getByTestId('metric-mttr')).toHaveTextContent('9,0 s')
    expect(screen.queryByText('EN COURS')).not.toBeInTheDocument()
  })
  it('MTTR live pendant un incident ouvert', () => {
    const inc = latestIncident(play(3))!
    render(<MetricsCards incident={inc} now={Date.parse(inc.detectedAt) + 12_500} />)
    expect(screen.getByTestId('metric-mttr')).toHaveTextContent('12,5 s')
    expect(screen.getByText('EN COURS')).toBeInTheDocument()
  })
  it('sans incident : tirets', () => {
    render(<MetricsCards incident={null} now={0} />)
    expect(screen.getByTestId('metric-mttd')).toHaveTextContent('--')
    expect(screen.getByTestId('metric-mttr')).toHaveTextContent('--')
  })
})

describe('VerificationCard / ServicesGrid / GrafanaLinks', () => {
  it('dernière vérification : succès avec identifiant', () => {
    render(<VerificationCard verify={play(5).lastVerification} />)
    expect(screen.getByTestId('verification')).toHaveAttribute('data-ok', 'true')
    expect(screen.getByText('tx-verify-42')).toBeInTheDocument()
    expect(screen.getByText('87 ms')).toBeInTheDocument()
  })
  it('vérification absente', () => {
    render(<VerificationCard verify={null} />)
    expect(screen.getByText('Aucune vérification reçue.')).toBeInTheDocument()
  })
  it('services : statut textuel (pas seulement la couleur)', () => {
    render(<ServicesGrid services={[{ name: 'waf', status: 'up' }, { name: 'payment-api', status: 'down' }, { name: 'auth', status: 'degraded' }]} />)
    expect(screen.getByText('OPÉRATIONNEL')).toBeInTheDocument()
    expect(screen.getByText('HORS SERVICE')).toBeInTheDocument()
    expect(screen.getByText('DÉGRADÉ')).toBeInTheDocument()
  })
  it('liens Grafana : base configurable, ouverture sécurisée', () => {
    render(<GrafanaLinks base="http://grafana.local:3000" />)
    const links = screen.getAllByRole('link')
    expect(links.map((l) => l.getAttribute('href'))).toEqual(grafanaLinks('http://grafana.local:3000').map((l) => l.href))
    for (const l of links) {
      expect(l).toHaveAttribute('target', '_blank')
      expect(l.getAttribute('rel')).toContain('noopener')
    }
  })
})
