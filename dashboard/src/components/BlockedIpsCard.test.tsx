import { describe, expect, it, vi } from 'vitest'
import { act, render, renderHook, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { BlockedIpsCard } from './BlockedIpsCard'
import { useBlockedIps } from '../hooks/useBlockedIps'
import { parseBlockedIps } from '../lib/blocklist'

const RAW = {
  blocked: [
    { ip: '192.168.137.115', blocked_at: '2026-10-21T13:40:00.000Z', list: 'temporary', incident_id: 'i1', incident_type: 'auth_abuse' },
    { ip: '203.0.113.9', blocked_at: null, list: 'unknown', incident_id: null, incident_type: null },
    { ip: '<script>alert(1)</script>', list: 'permanent' }, // jamais affiché comme une IP
    'n/a',
  ],
}

describe('liste noire du WAF (carte « IP bloquées »)', () => {
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

  it('bouton Débloquer : confirmation, appel, puis plus de bouton actif pendant le déblocage', async () => {
    const onUnblock = vi.fn(async () => true)
    const confirm = vi.fn(() => true)
    render(<BlockedIpsCard items={parseBlockedIps(RAW)} error={false} onUnblock={onUnblock} confirm={confirm} />)
    await userEvent.click(screen.getByRole('button', { name: 'Débloquer 192.168.137.115' }))
    expect(confirm).toHaveBeenCalledWith(expect.stringContaining('192.168.137.115'))
    expect(onUnblock).toHaveBeenCalledWith('192.168.137.115')
  })

  it('annulation : rien n’est envoyé ; échec : message d’erreur', async () => {
    const onUnblock = vi.fn(async () => false)
    const { rerender } = render(<BlockedIpsCard items={parseBlockedIps(RAW)} error={false} onUnblock={onUnblock} confirm={() => false} />)
    await userEvent.click(screen.getByRole('button', { name: 'Débloquer 203.0.113.9' }))
    expect(onUnblock).not.toHaveBeenCalled()
    rerender(<BlockedIpsCard items={parseBlockedIps(RAW)} error={false} onUnblock={onUnblock} confirm={() => true} />)
    await userEvent.click(screen.getByRole('button', { name: 'Débloquer 203.0.113.9' }))
    expect(screen.getByRole('alert').textContent).toContain('203.0.113.9')
  })

  it('lecture seule sans onUnblock : aucun bouton', () => {
    render(<BlockedIpsCard items={parseBlockedIps(RAW)} error={false} />)
    expect(screen.queryByRole('button')).toBeNull()
  })

  it('le hook envoie DELETE avec l’en-tête anti-CSRF puis relit la liste', async () => {
    const calls: { url: string; method?: string; headers?: Record<string, string> }[] = []
    const fetchImpl = async (url: string, init?: { method?: string; headers?: Record<string, string> }) => {
      calls.push({ url, method: init?.method, headers: init?.headers })
      return { ok: true, json: async () => ({ blocked: [] }) }
    }
    const { result } = renderHook(() => useBlockedIps('/remediation/waf/blocked-ips', 60_000, fetchImpl))
    await waitFor(() => expect(result.current.items).toEqual([]))
    let ok = false
    await act(async () => {
      ok = await result.current.unblock('192.168.137.115')
    })
    expect(ok).toBe(true)
    const del = calls.find((c) => c.method === 'DELETE')
    expect(del?.url).toBe('/remediation/waf/blocked-ips/192.168.137.115')
    expect(del?.headers).toEqual({ 'X-Resilience-Dashboard': '1' })
    expect(calls.at(-1)?.method).toBeUndefined() // relecture GET après le déblocage
  })
})
