import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { IncidentReportPanel, OperatorCommandPanel } from './OperatorTools'
import { initialState, latestIncident, reducer } from '../lib/state'
import { parseStreamMessage } from '../lib/parse'
import { FULL_SEQUENCE } from '../test/fixtures'
import { OPERATOR_TOKEN_KEY } from '../lib/operatorToken'

const OP = 'operator-token-0123456789abcdef'

const incidentAfter = (n: number) =>
  latestIncident(
    FULL_SEQUENCE.slice(0, n).reduce((s, [name, data]) => {
      const r = parseStreamMessage(name, JSON.stringify(data))
      if (!r.ok) throw new Error(r.error)
      return reducer(s, { type: 'message', message: r.value })
    }, initialState),
  )

const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
let fetchMock: ReturnType<typeof vi.fn>
beforeEach(() => {
  fetchMock = vi.fn()
  vi.stubGlobal('fetch', fetchMock)
  sessionStorage.clear()
})
afterEach(() => vi.unstubAllGlobals())

const calls = () => fetchMock.mock.calls.map(([url, init]) => [url, JSON.parse((init as RequestInit).body as string)])
const authOf = (i: number) => ((fetchMock.mock.calls[i]?.[1] as RequestInit | undefined)?.headers as Record<string, string> | undefined)?.Authorization

describe('IncidentReportPanel', () => {
  it('résumé DSI : POST /summarize avec l’incident, texte + badge mode dégradé', async () => {
    fetchMock.mockResolvedValue(json(200, { summary: 'Le paiement a été rétabli.', degraded: true, model: 'fallback' }))
    render(<IncidentReportPanel incident={incidentAfter(5)} />)
    await userEvent.click(screen.getByRole('button', { name: 'Résumé pour la direction' }))
    expect(await screen.findByText('Le paiement a été rétabli.')).toBeInTheDocument()
    expect(screen.getByText('mode dégradé')).toBeInTheDocument()
    const [url, body] = calls()[0]!
    expect(url).toBe('/assistant/api/v1/summarize')
    expect(body.incident.id).toBe('inc-001')
  })

  it('erreur de l’assistant affichée en clair', async () => {
    fetchMock.mockResolvedValue(json(422, { error: { code: 'incident_too_large', message: 'trop gros', request_id: 'r' } }))
    render(<IncidentReportPanel incident={incidentAfter(5)} />)
    await userEvent.click(screen.getByRole('button', { name: 'Résumé pour la direction' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('incident_too_large : trop gros')
  })

  it('post-mortem : désactivé tant que l’incident est en cours', () => {
    render(<IncidentReportPanel incident={incidentAfter(3)} />)
    expect(screen.getByRole('button', { name: 'Générer le post-mortem' })).toBeDisabled()
  })

  it('post-mortem : télécharge postmortem-<id>.md', async () => {
    fetchMock.mockResolvedValue(json(200, { markdown: '# PM', degraded: false, model: 'm' }))
    const createObjectURL = vi.fn(() => 'blob:pm')
    Object.assign(URL, { createObjectURL, revokeObjectURL: vi.fn() }) // absents de jsdom
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
      expect(this.download).toBe('postmortem-inc-001.md')
    })
    render(<IncidentReportPanel incident={incidentAfter(5)} />)
    await userEvent.click(screen.getByRole('button', { name: 'Générer le post-mortem' }))
    await vi.waitFor(() => expect(click).toHaveBeenCalledOnce())
    expect(calls()[0]![0]).toBe('/assistant/api/v1/postmortem')
    expect(createObjectURL).toHaveBeenCalledWith(expect.any(Blob))
    click.mockRestore()
  })
})

describe('OperatorCommandPanel', () => {
  const proposal = { action: 'waf_block_ip', params: { source: '192.168.137.50' }, explanation: 'Bloquer cette IP au WAF.' }
  const propose = async () => {
    render(<OperatorCommandPanel />)
    await userEvent.type(screen.getByLabelText('Commande'), "bloque l'IP 192.168.137.50")
    await userEvent.click(screen.getByRole('button', { name: 'Proposer' }))
  }

  it('propose -> Confirmer -> jeton opérateur -> /remediation/manual-actions, statut affiché', async () => {
    fetchMock
      .mockResolvedValueOnce(json(200, { proposal, message: 'ok', degraded: false }))
      .mockResolvedValueOnce(json(200, { incident_id: 'man-1', action: 'waf_block_ip', status: 'dry_run', detail: 'simulé' }))
    await propose()
    expect(await screen.findByText('Bloquer cette IP au WAF.')).toBeInTheDocument()
    expect(fetchMock).toHaveBeenCalledOnce() // rien d'exécuté sans clic
    await userEvent.type(screen.getByLabelText('Motif (optionnel)'), 'scan')
    await userEvent.click(screen.getByRole('button', { name: 'Confirmer' }))
    expect(fetchMock).toHaveBeenCalledOnce() // ni exécuté sans jeton opérateur
    const field = screen.getByLabelText(/Jeton opérateur requis/)
    expect(field).toHaveAttribute('type', 'password')
    await userEvent.type(field, OP)
    await userEvent.click(screen.getByRole('button', { name: 'Valider' }))
    expect(await screen.findByText('dry_run')).toBeInTheDocument()
    expect(calls()).toEqual([
      ['/assistant/api/v1/propose', { command: "bloque l'IP 192.168.137.50" }],
      ['/remediation/manual-actions', { action: 'waf_block_ip', params: { source: '192.168.137.50' }, reason: 'scan' }],
    ])
    // Le jeton ne part que vers le moteur, jamais vers l'assistant.
    expect(authOf(0)).toBeUndefined()
    expect(authOf(1)).toBe(`Bearer ${OP}`)
    expect(sessionStorage.getItem(OPERATOR_TOKEN_KEY)).toBe(OP)
  })

  it('jeton refusé (401) : message clair et jeton oublié', async () => {
    sessionStorage.setItem(OPERATOR_TOKEN_KEY, 'mauvais-jeton-0000000000')
    fetchMock
      .mockResolvedValueOnce(json(200, { proposal, message: 'ok', degraded: false }))
      .mockResolvedValueOnce(json(401, { error: { code: 'unauthorized', message: 'unauthorized', request_id: 'r' } }))
    await propose()
    await userEvent.click(await screen.findByRole('button', { name: 'Confirmer' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('401')
    expect(sessionStorage.getItem(OPERATOR_TOKEN_KEY)).toBeNull()
  })

  it('jeton de service présenté (403) : message explicite', async () => {
    sessionStorage.setItem(OPERATOR_TOKEN_KEY, OP)
    fetchMock
      .mockResolvedValueOnce(json(200, { proposal, message: 'ok', degraded: false }))
      .mockResolvedValueOnce(json(403, { error: { code: 'operator_token_required', message: 'x', request_id: 'r' } }))
    await propose()
    await userEvent.click(await screen.findByRole('button', { name: 'Confirmer' }))
    expect(await screen.findByRole('alert')).toHaveTextContent("n'est pas le jeton opérateur")
  })

  it('annuler la saisie du jeton : rien n’est exécuté', async () => {
    fetchMock.mockResolvedValueOnce(json(200, { proposal, message: 'ok', degraded: false }))
    await propose()
    await userEvent.click(await screen.findByRole('button', { name: 'Confirmer' }))
    const form = screen.getByLabelText(/Jeton opérateur requis/).closest('form') as HTMLFormElement
    await userEvent.click(within(form).getByRole('button', { name: 'Annuler' }))
    expect(fetchMock).toHaveBeenCalledOnce()
    expect(screen.queryByLabelText(/Jeton opérateur requis/)).not.toBeInTheDocument()
  })

  it('Annuler n’appelle rien', async () => {
    fetchMock.mockResolvedValueOnce(json(200, { proposal, message: 'ok', degraded: false }))
    await propose()
    await userEvent.click(await screen.findByRole('button', { name: 'Annuler' }))
    expect(fetchMock).toHaveBeenCalledOnce()
    expect(screen.queryByRole('button', { name: 'Confirmer' })).not.toBeInTheDocument()
  })

  it('proposal null : message affiché, aucun bouton Confirmer', async () => {
    fetchMock.mockResolvedValueOnce(json(200, { proposal: null, message: 'Commande non reconnue.', degraded: false }))
    await propose()
    expect(await screen.findByText('Commande non reconnue.')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Confirmer' })).not.toBeInTheDocument()
  })

  it('422 du moteur (action_refused) affiché en clair', async () => {
    sessionStorage.setItem(OPERATOR_TOKEN_KEY, OP)
    fetchMock
      .mockResolvedValueOnce(json(200, { proposal: { ...proposal, action: 'restart_service', params: { service: 'db' } }, message: 'ok', degraded: false }))
      .mockResolvedValueOnce(json(422, { error: { code: 'action_refused', message: 'service hors liste blanche', request_id: 'r' } }))
    await propose()
    await userEvent.click(await screen.findByRole('button', { name: 'Confirmer' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('action_refused : service hors liste blanche')
  })

  it('moteur/assistant injoignable (mode simulé sans stack) : erreur propre', async () => {
    fetchMock.mockRejectedValueOnce(new TypeError('Failed to fetch'))
    await propose()
    expect(await screen.findByRole('alert')).toHaveTextContent('Service injoignable')
  })
})
