import { describe, expect, it, vi } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { GrafanaLinks, exploreLink, grafanaLinks } from './GrafanaLinks'
import { ActionsPanel, EvidencePanel, PlaybooksPanel, SignalsPanel, actionRows } from './IncidentDetails'
import { IncidentTimeline } from './IncidentTimeline'
import { MetricsCards, ScoreCard, VerificationCard } from './MetricsCards'
import { PhaseBanner } from './PhaseBanner'
import { ScoreChart, WINDOW_MS, chartPoints } from './ScoreChart'
import { ServicesGrid } from './ServicesGrid'
import { derivePhase, initialState, latestIncident, reducer } from '../lib/state'
import { parseStreamMessage } from '../lib/parse'
import { FULL_SEQUENCE } from '../test/fixtures'
import type { DashboardState, Phase, ScoreSample } from '../types/events'

function play(n: number): DashboardState {
  return FULL_SEQUENCE.slice(0, n).reduce((s, [name, data]) => {
    const r = parseStreamMessage(name, JSON.stringify(data))
    if (!r.ok) throw new Error(r.error)
    return reducer(s, { type: 'message', message: r.value })
  }, initialState)
}

const failed = () =>
  reducer(play(3), {
    type: 'message',
    message: { kind: 'remediation_failed', ts: '2026-10-21T09:15:00.000Z', incidentId: 'inc-001', reason: 'restart refusé' },
  })

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

  it.each([
    [0, 'before', 'Système nominal', 'aucun incident en cours'],
    [2, 'during', 'Remédiation automatique en cours', 'Saturation du service détecté sur payment-api'],
    [5, 'after', 'vérification OK', 'rétabli en 9,0 s'],
  ] as const)('à partir du flux (%i messages) : phase %s', (n, phase, caption, line) => {
    const s = play(n)
    expect(derivePhase(s)).toBe(phase)
    render(<PhaseBanner phase={derivePhase(s)} incident={latestIncident(s)} />)
    expect(screen.getByRole('listitem', { current: 'step' })).toHaveTextContent(caption)
    expect(screen.getByTestId('headline')).toHaveTextContent(line)
  })

  it('APRÈS : badge « Reprise sans intervention humaine » (zero-touch)', () => {
    const { rerender } = render(<PhaseBanner phase="during" incident={latestIncident(play(2))} />)
    expect(screen.queryByText('Reprise sans intervention humaine')).not.toBeInTheDocument()
    rerender(<PhaseBanner phase="after" incident={latestIncident(play(5))} />)
    expect(screen.getByText('Reprise sans intervention humaine')).toBeInTheDocument()
  })

  it("escalade : PENDANT affiche l'échec et sa raison", () => {
    const s = failed()
    render(<PhaseBanner phase={derivePhase(s)} incident={latestIncident(s)} />)
    expect(screen.getByRole('listitem', { current: 'step' })).toHaveTextContent('escalade')
    expect(screen.getByTestId('headline')).toHaveTextContent('restart refusé')
  })
})

describe('IncidentTimeline', () => {
  it('sans incident : 4 étapes en attente et message nominal', () => {
    render(<IncidentTimeline incident={null} />)
    expect(screen.getByText(/fonctionne normalement/)).toBeInTheDocument()
    expect(screen.getAllByRole('listitem').map((s) => s.getAttribute('data-status'))).toEqual(['pending', 'pending', 'pending', 'pending'])
  })
  it('incident résolu : 4 étapes dans l’ordre, toutes terminées, décalages depuis la détection', () => {
    render(<IncidentTimeline incident={latestIncident(play(5))} />)
    const steps = within(screen.getByRole('list', { name: 'Étapes de la remédiation' })).getAllByRole('listitem')
    expect(steps.map((s) => s.getAttribute('data-step'))).toEqual(['detection', 'decision', 'action', 'verification'])
    expect(steps.every((s) => s.getAttribute('data-status') === 'done')).toBe(true)
    expect(screen.getByText(/inc-001 · Saturation du service · payment-api/)).toBeInTheDocument()
    expect(steps[3]).toHaveTextContent('+9,0 s')
  })
  it('incident en cours : une seule étape active, chronomètre live', () => {
    const inc = latestIncident(play(2))!
    render(<IncidentTimeline incident={inc} now={Date.parse(inc.detectedAt) + 3_000} />)
    const steps = screen.getAllByRole('listitem')
    expect(steps.map((s) => s.getAttribute('data-status'))).toEqual(['done', 'done', 'active', 'pending'])
    expect(steps[2]).toHaveTextContent('+3,0 s…')
  })
})

describe('ScoreCard', () => {
  it('sans donnée : tiret, niveau none', () => {
    render(<ScoreCard score={null} history={[]} />)
    expect(screen.getByTestId('score-gauge')).toHaveAttribute('data-level', 'none')
    expect(screen.getByTestId('score-value')).toHaveTextContent('—')
    expect(screen.getByText('seuil 0.60')).toBeInTheDocument()
  })
  it('score au-dessus du seuil : alerte', () => {
    const s = play(1)
    render(<ScoreCard score={s.score} history={s.history} />)
    expect(screen.getByTestId('score-value')).toHaveTextContent('0.87')
    expect(screen.getByTestId('score-gauge')).toHaveAttribute('data-level', 'alert')
    expect(screen.getByText('au-dessus du seuil')).toBeInTheDocument()
    expect(screen.getByText(/payment-api/)).toBeInTheDocument()
  })
})

describe('ScoreChart', () => {
  const now = Date.parse('2026-10-21T09:15:00.000Z')
  const at = (s: number, score: number, service = 'payment-api'): ScoreSample => ({ ts: new Date(now - s * 1000).toISOString(), service, score, threshold: 0.6 })

  it('géométrie : bord gauche = -120 s, bord droit = maintenant, y inversé', () => {
    expect(chartPoints([at(120, 0), at(60, 0.5), at(0, 1)], now)).toEqual([
      [0, 200],
      [300, 100],
      [600, 0],
    ])
  })
  it('ignore les points hors fenêtre', () => {
    expect(chartPoints([at(WINDOW_MS / 1000 + 10, 0.3), at(1, 0.3)], now)).toHaveLength(1)
  })
  it('onglets par service, sélection remontée', async () => {
    const onFocus = vi.fn()
    const history = [at(2, 0.2), at(2, 0.3, 'auth'), at(1, 0.2), at(1, 0.3, 'auth')]
    render(<ScoreChart history={history} services={['payment-api', 'auth']} focus="payment-api" onFocus={onFocus} threshold={0.6} incident={null} now={now} />)
    expect(screen.getByRole('tab', { name: 'payment-api' })).toHaveAttribute('aria-selected', 'true')
    await userEvent.click(screen.getByRole('tab', { name: 'auth' }))
    expect(onFocus).toHaveBeenCalledWith('auth')
  })
  it('sans données : message d’attente ; marqueurs détection / vérifié sur le service de l’incident', () => {
    const { rerender } = render(<ScoreChart history={[]} services={[]} focus={null} onFocus={() => {}} threshold={0.6} incident={null} now={now} />)
    expect(screen.getByText("En attente d'événements score…")).toBeInTheDocument()
    const inc = latestIncident(play(5))!
    rerender(<ScoreChart history={[at(2, 0.2), at(1, 0.9)]} services={['payment-api']} focus="payment-api" onFocus={() => {}} threshold={0.6} incident={inc} now={now} />)
    expect(screen.getByText('Détection')).toBeInTheDocument()
    expect(screen.getByText('Vérifié')).toBeInTheDocument()
  })
})

describe('MetricsCards / VerificationCard', () => {
  it('MTTD/MTTR affichés pour un incident résolu', () => {
    render(<MetricsCards incident={latestIncident(play(5))} now={Date.parse('2026-10-21T09:20:00Z')} />)
    expect(screen.getByTestId('metric-mttd')).toHaveTextContent('4,2 s')
    expect(screen.getByTestId('metric-mttr')).toHaveTextContent('9,0 s')
    expect(screen.getByText('détection → service vérifié')).toBeInTheDocument()
  })
  it('MTTR live pendant un incident ouvert', () => {
    const inc = latestIncident(play(3))!
    render(<MetricsCards incident={inc} now={Date.parse(inc.detectedAt) + 12_500} />)
    expect(screen.getByTestId('metric-mttr')).toHaveTextContent('12,5 s')
    expect(screen.getByText('chronomètre en cours')).toBeInTheDocument()
  })
  it('sans incident : tirets', () => {
    render(<MetricsCards incident={null} now={0} />)
    expect(screen.getByTestId('metric-mttd')).toHaveTextContent('--')
    expect(screen.getByTestId('metric-mttr')).toHaveTextContent('--')
  })
  it('dernière vérification : succès, identifiant, durée et ancienneté', () => {
    const v = play(5).lastVerification!
    render(<VerificationCard verify={v} now={Date.parse(v.ts) + 4_000} />)
    expect(screen.getByTestId('verification')).toHaveAttribute('data-ok', 'true')
    expect(screen.getByText('tx-verify-42')).toBeInTheDocument()
    expect(screen.getByText('87')).toBeInTheDocument()
    expect(screen.getByText(/il y a 4 s/)).toBeInTheDocument()
  })
  it('vérification absente', () => {
    render(<VerificationCard verify={null} now={0} />)
    expect(screen.getByText('Aucune vérification reçue.')).toBeInTheDocument()
    expect(screen.getByText('aucune')).toBeInTheDocument()
  })
})

describe('ServicesGrid', () => {
  it('statut textuel (pas seulement la couleur) et décompte', () => {
    render(<ServicesGrid services={[{ name: 'waf', status: 'up' }, { name: 'payment-api', status: 'down' }, { name: 'auth', status: 'degraded' }]} />)
    expect(screen.getByText('Opérationnel')).toBeInTheDocument()
    expect(screen.getByText('Hors service')).toBeInTheDocument()
    expect(screen.getByText('Dégradé')).toBeInTheDocument()
    expect(screen.getByText('1/3 opérationnels')).toBeInTheDocument()
  })
  it('avant tout message health : en attente', () => {
    render(<ServicesGrid services={initialState.services} />)
    expect(screen.getByText('en attente de health')).toBeInTheDocument()
  })
})

describe('Détails d’incident', () => {
  it('actions : plan de la décision + résultat, « en cours » tant que non exécutée', () => {
    expect(actionRows(latestIncident(play(3))).map((r) => [r.type, r.result])).toEqual([
      ['waf_block_ip', 'ok'],
      ['restart_service', 'running'],
    ])
    render(<ActionsPanel incident={latestIncident(play(4))} />)
    expect(screen.getByText('2/2 réussie(s)')).toBeInTheDocument()
    expect(screen.getByText(/service=payment-api/)).toBeInTheDocument()
  })
  it('actions : un detail identique aux paramètres n’est pas répété', () => {
    const s = reducer(play(2), {
      type: 'message',
      message: { kind: 'remediation_action', ts: '2026-10-21T09:14:38.000Z', incidentId: 'inc-001', action: 'restart_service', result: 'ok', detail: 'service=payment-api', attempt: 1 },
    })
    expect(actionRows(latestIncident(s)).find((r) => r.type === 'restart_service')?.meta).toBe('service=payment-api — tentative 1')
  })
  it('actions : vide sans incident ; action hors plan conservée', () => {
    render(<ActionsPanel incident={null} />)
    expect(screen.getByText(/attend un événement remediation_started/)).toBeInTheDocument()
    const s = reducer(play(4), {
      type: 'message',
      message: { kind: 'remediation_action', ts: '2026-10-21T09:14:42.000Z', incidentId: 'inc-001', action: 'notify_operator', result: 'ok', detail: null, attempt: null },
    })
    expect(actionRows(latestIncident(s)).map((r) => r.type)).toEqual(['waf_block_ip', 'restart_service', 'notify_operator'])
  })
  it('signaux dominants : z-score signé', () => {
    render(<SignalsPanel incident={latestIncident(play(1))} />)
    expect(screen.getByText('req_per_s')).toBeInTheDocument()
    expect(screen.getByText('+9.2σ')).toBeInTheDocument()
  })
  it('playbooks : la règle de l’incident est surlignée', () => {
    render(<PlaybooksPanel incident={latestIncident(play(1))} />)
    const active = screen.getAllByRole('listitem').filter((li) => li.getAttribute('data-active') === 'true')
    expect(active.map((li) => li.getAttribute('data-playbook'))).toEqual(['service_flood'])
  })
  it('preuves : liens Explore Prometheus et Loki pré-remplis', () => {
    render(<EvidencePanel incident={latestIncident(play(1))} grafanaBase="http://g:3000" />)
    const links = screen.getAllByRole('link')
    expect(links).toHaveLength(2)
    expect(links[0]).toHaveAttribute('href', exploreLink('http://g:3000', 'prometheus', 'rate(resilience_http_requests_total[1m])'))
    expect(decodeURIComponent(links[1]!.getAttribute('href')!)).toContain('"datasource":"loki"')
  })
  it('preuves : rien sans anomalie', () => {
    const { container } = render(<EvidencePanel incident={null} grafanaBase="http://g:3000" />)
    expect(container).toBeEmptyDOMElement()
  })
})

describe('GrafanaLinks', () => {
  it('base configurable, ouverture sécurisée', () => {
    render(<GrafanaLinks base="http://grafana.local:3000" />)
    const links = screen.getAllByRole('link')
    expect(links.map((l) => l.getAttribute('href'))).toEqual(grafanaLinks('http://grafana.local:3000').map((l) => l.href))
    for (const l of links) {
      expect(l).toHaveAttribute('target', '_blank')
      expect(l.getAttribute('rel')).toContain('noopener')
    }
  })
})
