import { beforeEach, describe, expect, it, vi } from 'vitest'
import { act, render, renderHook, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { BlockedIpsCard } from './BlockedIpsCard'
import { useBlockedIps } from '../hooks/useBlockedIps'
import { parseBlockedIps } from '../lib/blocklist'
import { OPERATOR_TOKEN_KEY, operatorOutcome } from '../lib/operatorToken'

const OP = 'operator-token-0123456789abcdef'

const RAW = {
  blocked: [
    { ip: '192.168.137.115', blocked_at: '2026-10-21T13:40:00.000Z', list: 'temporary', incident_id: 'i1', incident_type: 'auth_abuse' },
    { ip: '203.0.113.9', blocked_at: null, list: 'unknown', incident_id: null, incident_type: null },
    { ip: '<script>alert(1)</script>', list: 'permanent' }, // jamais affiché comme une IP
    'n/a',
  ],
}

describe('liste noire du WAF (carte « IP bloquées »)', () => {
  beforeEach(() => sessionStorage.clear())

  it('parse la réponse du moteur et écarte les entrées invalides', () => {
    expect(parseBlockedIps(RAW)).toEqual([
      { ip: '192.168.137.115', blockedAt: '2026-10-21T13:40:00.000Z', list: 'temporary', incidentId: 'i1', incidentType: 'auth_abuse' },
      { ip: '203.0.113.9', blockedAt: null, list: 'unknown', incidentId: null, incidentType: null },
    ])
    for (const bad of [null, 'x', {}, { blocked: 'x' }]) expect(parseBlockedIps(bad)).toBeNull()
    expect(parseBlockedIps({ blocked: [] })).toEqual([])
  })

  it('affiche chaque IP avec sa liste et le type d’incident', () => {
    render(<BlockedIpsCard items={parseBlockedIps(RAW)} error={false} />)
    expect(screen.getByText('2 IPs')).toBeTruthy()
    const row = document.querySelector('[data-ip="192.168.137.115"]') as HTMLElement
    expect(row.textContent).toContain('auth_abuse')
    expect(row.textContent).toContain('Temporaire')
    expect(document.querySelector('[data-ip="203.0.113.9"]')?.textContent).toContain('ajoutée hors moteur')
  })

  it('états vide, chargement et moteur injoignable', () => {
    const { rerender } = render(<BlockedIpsCard items={[]} error={false} />)
    expect(screen.getByText('Aucune IP bloquée.')).toBeTruthy()
    rerender(<BlockedIpsCard items={null} error={false} />)
    expect(screen.getByText('chargement…')).toBeTruthy()
    rerender(<BlockedIpsCard items={null} error={true} />)
    expect(screen.getByText('moteur injoignable')).toBeTruthy()
  })

  it('le hook relève l’URL et garde la dernière liste connue en cas d’échec', async () => {
    let fail = false
    const calls: string[] = []
    const fetchImpl = async (url: string) => {
      calls.push(url)
      if (fail) throw new Error('down')
      return { ok: true, json: async () => RAW }
    }
    const { result, rerender } = renderHook(({ ms }) => useBlockedIps('/remediation/waf/blocked-ips', ms, fetchImpl), { initialProps: { ms: 20 } })
    await waitFor(() => expect(result.current.items?.length).toBe(2))
    expect(calls[0]).toBe('/remediation/waf/blocked-ips')
    fail = true
    rerender({ ms: 20 })
    await waitFor(() => expect(result.current.error).toBe(true))
    expect(result.current.items?.length).toBe(2)
  })

  it('pas de relève sans URL (simulation, tests)', () => {
    const { result } = renderHook(() => useBlockedIps(null))
    expect(result.current.items).toBeNull()
    expect(result.current.error).toBe(false)
  })

  it('bouton Débloquer : confirmation, jeton opérateur demandé au 1er usage, mémorisé pour la session', async () => {
    const onUnblock = vi.fn(async () => 'ok' as const)
    const confirm = vi.fn(() => true)
    render(<BlockedIpsCard items={parseBlockedIps(RAW)} error={false} onUnblock={onUnblock} confirm={confirm} />)
    await userEvent.click(screen.getByRole('button', { name: 'Débloquer 192.168.137.115' }))
    expect(confirm).toHaveBeenCalledWith(expect.stringContaining('192.168.137.115'))
    expect(onUnblock).not.toHaveBeenCalled() // rien ne part sans jeton
    const field = screen.getByLabelText(/Jeton opérateur requis/)
    expect(field.getAttribute('type')).toBe('password')
    await userEvent.type(field, OP)
    await userEvent.click(screen.getByRole('button', { name: 'Valider' }))
    expect(onUnblock).toHaveBeenCalledWith('192.168.137.115', OP)
    expect(sessionStorage.getItem(OPERATOR_TOKEN_KEY)).toBe(OP)
    expect(localStorage.getItem(OPERATOR_TOKEN_KEY)).toBeNull()
    // 2e déblocage : le jeton de la session est réutilisé, plus de saisie.
    await userEvent.click(screen.getByRole('button', { name: 'Débloquer 203.0.113.9' }))
    expect(onUnblock).toHaveBeenLastCalledWith('203.0.113.9', OP)
    expect(screen.queryByLabelText(/Jeton opérateur requis/)).toBeNull()
  })

  it('annulation (confirmation ou saisie du jeton) : rien n’est envoyé', async () => {
    const onUnblock = vi.fn(async () => 'ok' as const)
    const { rerender } = render(<BlockedIpsCard items={parseBlockedIps(RAW)} error={false} onUnblock={onUnblock} confirm={() => false} />)
    await userEvent.click(screen.getByRole('button', { name: 'Débloquer 203.0.113.9' }))
    expect(screen.queryByLabelText(/Jeton opérateur requis/)).toBeNull()
    rerender(<BlockedIpsCard items={parseBlockedIps(RAW)} error={false} onUnblock={onUnblock} confirm={() => true} />)
    await userEvent.click(screen.getByRole('button', { name: 'Débloquer 203.0.113.9' }))
    await userEvent.click(screen.getByRole('button', { name: 'Annuler' }))
    expect(onUnblock).not.toHaveBeenCalled()
    expect(sessionStorage.getItem(OPERATOR_TOKEN_KEY)).toBeNull()
  })

  it.each([
    ['unauthorized', '401'],
    ['forbidden', '403'],
    ['unavailable', '503'],
    ['error', 'injoignable'],
  ] as const)('échec %s : message clair', async (outcome, text) => {
    sessionStorage.setItem(OPERATOR_TOKEN_KEY, OP)
    const onUnblock = vi.fn(async () => outcome)
    render(<BlockedIpsCard items={parseBlockedIps(RAW)} error={false} onUnblock={onUnblock} confirm={() => true} />)
    await userEvent.click(screen.getByRole('button', { name: 'Débloquer 203.0.113.9' }))
    const alert = screen.getByRole('alert').textContent ?? ''
    expect(alert).toContain('203.0.113.9')
    expect(alert).toContain(text)
  })

  it('401/403 effacent le jeton mémorisé (il sera redemandé), pas les autres échecs', () => {
    for (const [status, cleared] of [[401, true], [403, true], [503, false], [500, false], [200, false]] as const) {
      sessionStorage.setItem(OPERATOR_TOKEN_KEY, OP)
      operatorOutcome(status)
      expect(sessionStorage.getItem(OPERATOR_TOKEN_KEY) === null).toBe(cleared)
    }
  })

  it('lecture seule sans onUnblock : aucun bouton', () => {
    render(<BlockedIpsCard items={parseBlockedIps(RAW)} error={false} />)
    expect(screen.queryByRole('button')).toBeNull()
  })

  it('le hook envoie DELETE avec l’en-tête anti-CSRF et le jeton OPÉRATEUR, puis relit la liste', async () => {
    const calls: { url: string; method?: string; headers?: Record<string, string> }[] = []
    let deleteStatus = 200
    const fetchImpl = async (url: string, init?: { method?: string; headers?: Record<string, string> }) => {
      calls.push({ url, method: init?.method, headers: init?.headers })
      const status = init?.method === 'DELETE' ? deleteStatus : 200
      return { ok: status < 300, status, json: async () => ({ blocked: [] }) }
    }
    const { result } = renderHook(() => useBlockedIps('/remediation/waf/blocked-ips', 60_000, fetchImpl))
    await waitFor(() => expect(result.current.items).toEqual([]))
    let outcome = ''
    await act(async () => {
      outcome = await result.current.unblock('192.168.137.115', OP)
    })
    expect(outcome).toBe('ok')
    const del = calls.find((c) => c.method === 'DELETE')
    expect(del?.url).toBe('/remediation/waf/blocked-ips/192.168.137.115')
    expect(del?.headers).toEqual({ 'X-Resilience-Dashboard': '1', Authorization: `Bearer ${OP}` })
    expect(calls.at(-1)?.method).toBeUndefined() // relecture GET après le déblocage
    // Les lectures ne portent jamais le jeton opérateur (nginx injecte le jeton de service).
    expect(calls.filter((c) => c.method !== 'DELETE').every((c) => !c.headers?.Authorization)).toBe(true)
    deleteStatus = 401
    await act(async () => {
      outcome = await result.current.unblock('192.168.137.115', 'mauvais-jeton')
    })
    expect(outcome).toBe('unauthorized')
  })
})
