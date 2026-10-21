import { describe, expect, it, vi } from 'vitest'
import { createApiClient } from './client'
import { createEndpoints } from './index'
import { decodeJwtClaims, decodeJwtExp } from './tokenStore'
import { parseAccounts, parseLogin, parseTransaction } from './parsers'
import { fakeJwt, jsonResponse } from '../test/helpers'

function endpointsWith(handler: (url: string, init?: RequestInit) => Response) {
  const f = vi.fn(async (u: RequestInfo | URL, init?: RequestInit) => handler(String(u), init))
  const client = createApiClient({ baseUrl: '', getToken: () => 't', fetchImpl: f as unknown as typeof fetch })
  return { api: createEndpoints(client), f }
}

describe('endpoints /api/v1', () => {
  it('login : POST /api/v1/login et parse access_token', async () => {
    const { api, f } = endpointsWith(() => jsonResponse({ access_token: 'jwt', token_type: 'bearer', expires_in: 900 }))
    const res = await api.login({ username: 'demo01', password: 'pw' })
    expect(res).toEqual({ accessToken: 'jwt', tokenType: 'bearer', expiresIn: 900 })
    const [url, init] = f.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toBe('/api/v1/login')
    expect(init.method).toBe('POST')
  })

  it('getStatus : GET /api/v1/status sans jeton ; 503 degraded = erreur serveur', async () => {
    const { api, f } = endpointsWith(() => jsonResponse({ status: 'ok', checked_at: '2026-10-21T10:00:00Z' }))
    expect(await api.getStatus()).toEqual({ status: 'ok', checkedAt: '2026-10-21T10:00:00Z' })
    const [url, init] = f.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toBe('/api/v1/status')
    expect((init.headers as Record<string, string>).Authorization).toBeUndefined()
    const down = endpointsWith(() => jsonResponse({ status: 'degraded', checked_at: '2026-10-21T10:00:00Z' }, 503))
    await expect(down.api.getStatus()).rejects.toMatchObject({ status: 503 })
  })

  it('getAccounts : GET /api/v1/accounts, centimes payment-api -> euros', async () => {
    const { api, f } = endpointsWith(() =>
      jsonResponse([{ id: 1, iban_fake: 'FR76 0000 0001', balance_cents: 125050, currency: 'EUR' }]),
    )
    const accounts = await api.getAccounts()
    expect(accounts).toEqual([{ id: '1', owner: null, label: 'FR76 0000 0001', iban: 'FR76 0000 0001', balance: 1250.5, currency: 'EUR' }])
    expect((f.mock.calls[0] as unknown as [string])[0]).toBe('/api/v1/accounts')
  })

  it('createTransaction : POST avec src/dst_account entiers et amount_cents', async () => {
    const { api, f } = endpointsWith(() =>
      jsonResponse(
        { id: 42, src_account: 1, dst_account: 2, amount_cents: 1000, status: 'created' },
        201,
      ),
    )
    const tx = await api.createTransaction({ from_account: '1', to_account: '2', amount: 10 })
    expect(tx).toMatchObject({ id: '42', status: 'created', fromAccount: '1', toAccount: '2', amount: 10 })
    const [url, init] = f.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toBe('/api/v1/transactions')
    expect(JSON.parse(init.body as string)).toEqual({ src_account: 1, dst_account: 2, amount_cents: 1000 })
  })

  it('listTransactions : accepte une liste TransactionOut (centimes)', async () => {
    const { api } = endpointsWith(() =>
      jsonResponse([{ id: 7, src_account: 1, dst_account: 2, amount_cents: 500, status: 'rejected' }]),
    )
    const txs = await api.listTransactions()
    expect(txs).toHaveLength(1)
    expect(txs[0]).toMatchObject({ status: 'rejected', amount: 5, currency: 'EUR', fromAccount: '1', toAccount: '2' })
  })
})

describe('parseurs', () => {
  it('rejette une réponse login sans jeton', () => {
    expect(() => parseLogin({})).toThrowError(/Jeton absent/)
  })
  it('rejette un compte sans solde numérique', () => {
    expect(() => parseAccounts([{ id: 'a', balance_cents: 'abc' }])).toThrowError()
  })
  it('tolère une transaction sans horodatage (payment-api n’en fournit pas)', () => {
    const tx = parseTransaction({ id: 1, src_account: 1, dst_account: 2, amount_cents: 100, status: 'created' })
    expect(tx).toMatchObject({ id: '1', fromAccount: '1', toAccount: '2', amount: 1, createdAt: '' })
  })
})

describe('decodeJwtExp', () => {
  it('lit le claim exp', () => {
    expect(decodeJwtExp(fakeJwt(1_800_000_000))).toBe(1_800_000_000)
  })
  it('renvoie null pour un jeton illisible', () => {
    expect(decodeJwtExp('pas-un-jwt')).toBeNull()
  })
  it('lit le claim sub (username affiché dans la session)', () => {
    expect(decodeJwtClaims(fakeJwt(1_800_000_000))).toEqual({ sub: 'demo01', exp: 1_800_000_000 })
    expect(decodeJwtClaims('pas-un-jwt')).toEqual({ sub: null, exp: null })
  })
})
