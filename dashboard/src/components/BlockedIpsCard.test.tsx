import { describe, expect, it } from 'vitest'
import { render, renderHook, screen, waitFor } from '@testing-library/react'
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
    expect(result.current).toEqual({ items: null, error: false })
  })
})
