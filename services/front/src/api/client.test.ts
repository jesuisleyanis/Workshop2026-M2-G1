import { describe, expect, it, vi } from 'vitest'
import { createApiClient } from './client'
import { ApiError } from './errors'
import { jsonResponse } from '../test/helpers'

function make(fetchImpl: typeof fetch, extra: Partial<Parameters<typeof createApiClient>[0]> = {}) {
  const onUnauthorized = vi.fn()
  const client = createApiClient({
    baseUrl: 'https://waf.local',
    getToken: () => 'tok123',
    onUnauthorized,
    fetchImpl,
    ...extra,
  })
  return { client, onUnauthorized }
}

describe('client API centralisé', () => {
  it('reportRecovery:false : un 429 ou un 200 ne vaut pas reprise, un 5xx reste signalé', async () => {
    const onAvailability = vi.fn()
    let status = 429
    const f = vi.fn(async () => jsonResponse({ status: 'ok', checked_at: 'x' }, status))
    const { client } = make(f as unknown as typeof fetch, { onAvailability })
    await client.request('/api/v1/status', { auth: false, reportRecovery: false }).catch(() => {})
    status = 200
    await client.request('/api/v1/status', { auth: false, reportRecovery: false })
    expect(onAvailability).not.toHaveBeenCalled()
    status = 503
    await client.request('/api/v1/status', { auth: false, reportRecovery: false }).catch(() => {})
    expect(onAvailability).toHaveBeenCalledWith(false, expect.any(Number))
  })

  it('préfixe la base, envoie le Bearer et parse le JSON', async () => {
    const f = vi.fn(async () => jsonResponse([{ id: 'a' }]))
    const { client } = make(f as unknown as typeof fetch)
    const out = await client.request('/api/v1/accounts')
    expect(out).toEqual([{ id: 'a' }])
    const [url, init] = f.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toBe('https://waf.local/api/v1/accounts')
    expect((init.headers as Record<string, string>).Authorization).toBe('Bearer tok123')
  })

  it("n'envoie pas de Bearer pour auth:false et sérialise le corps JSON", async () => {
    const f = vi.fn(async () => jsonResponse({ access_token: 'x' }))
    const { client } = make(f as unknown as typeof fetch)
    await client.request('/api/v1/login', { method: 'POST', body: { username: 'u', password: 'p' }, auth: false })
    const [, init] = f.mock.calls[0] as unknown as [string, RequestInit]
    const headers = init.headers as Record<string, string>
    expect(headers.Authorization).toBeUndefined()
    expect(headers['Content-Type']).toBe('application/json')
    expect(init.body).toBe('{"username":"u","password":"p"}')
  })

  it("normalise l'erreur du contrat { error: { code, message, request_id } }", async () => {
    const f = vi.fn(async () =>
      jsonResponse({ error: { code: 'insufficient_funds', message: 'Solde insuffisant', request_id: 'rid-1' } }, 422),
    )
    const { client } = make(f as unknown as typeof fetch)
    const err = await client.request('/api/v1/transactions', { method: 'POST', body: {} }).catch((e) => e)
    expect(err).toBeInstanceOf(ApiError)
    expect(err).toMatchObject({ status: 422, code: 'insufficient_funds', message: 'Solde insuffisant', requestId: 'rid-1' })
  })

  it('repli générique si le corps ne suit pas le contrat (ex. page HTML du WAF)', async () => {
    const f = vi.fn(async () => new Response('<html>blocked</html>', { status: 403 }))
    const { client } = make(f as unknown as typeof fetch)
    const err = (await client.request('/x').catch((e) => e)) as ApiError
    expect(err.code).toBe('http_403')
    expect(err.status).toBe(403)
  })

  it('un 401 authentifié déclenche onUnauthorized', async () => {
    const f = vi.fn(async () => jsonResponse({ error: { code: 'token_expired', message: 'Expiré' } }, 401))
    const { client, onUnauthorized } = make(f as unknown as typeof fetch)
    await expect(client.request('/api/v1/accounts')).rejects.toMatchObject({ status: 401 })
    expect(onUnauthorized).toHaveBeenCalledTimes(1)
  })

  it('un 401 sur login (auth:false) ne déclenche pas la déconnexion', async () => {
    const f = vi.fn(async () => jsonResponse({ error: { code: 'invalid_credentials', message: 'Non' } }, 401))
    const { client, onUnauthorized } = make(f as unknown as typeof fetch)
    await expect(client.request('/api/v1/login', { method: 'POST', body: {}, auth: false })).rejects.toMatchObject({
      code: 'invalid_credentials',
    })
    expect(onUnauthorized).not.toHaveBeenCalled()
  })

  it('transforme une panne réseau en ApiError network_error', async () => {
    const f = vi.fn(async () => {
      throw new TypeError('Failed to fetch')
    })
    const { client } = make(f as unknown as typeof fetch)
    const err = (await client.request('/x').catch((e) => e)) as ApiError
    expect(err.code).toBe('network_error')
    expect(err.isNetwork).toBe(true)
  })

  it('timeout : abandonne la requête et renvoie ApiError timeout', async () => {
    const f = vi.fn(
      (_url: string, init?: RequestInit) =>
        new Promise<Response>((_res, rej) => {
          init?.signal?.addEventListener('abort', () => rej(new DOMException('aborted', 'AbortError')))
        }),
    )
    const { client } = make(f as unknown as typeof fetch, { timeoutMs: 20 })
    const err = (await client.request('/slow').catch((e) => e)) as ApiError
    expect(err.code).toBe('timeout')
  })

  it('204 sans corps => null', async () => {
    const f = vi.fn(async () => new Response(null, { status: 204 }))
    const { client } = make(f as unknown as typeof fetch)
    expect(await client.request('/x')).toBeNull()
  })
})
