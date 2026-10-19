import { describe, expect, it, vi } from 'vitest'
import { createApiClient } from './client'
import { createEndpoints } from './index'
import { decodeJwtExp } from './tokenStore'
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

  it('getAccounts : GET /api/v1/accounts, décimaux en chaîne acceptés', async () => {
    const { api, f } = endpointsWith(() => jsonResponse([{ id: 'FR01', balance: '1250.50', currency: 'EUR', label: 'Courant' }]))
    const accounts = await api.getAccounts()
    expect(accounts).toEqual([{ id: 'FR01', owner: null, label: 'Courant', balance: 1250.5, currency: 'EUR' }])
    expect((f.mock.calls[0] as unknown as [string])[0]).toBe('/api/v1/accounts')
  })

  it('createTransaction : POST /api/v1/transactions avec from_account/to_account/amount', async () => {
    const { api, f } = endpointsWith(() =>
      jsonResponse(
        { id: 'tx1', from_account: 'FR01', to_account: 'FR02', amount: 10, currency: 'EUR', status: 'created', created_at: '2026-10-21T09:14:33Z' },
        201,
      ),
    )
    const tx = await api.createTransaction({ from_account: 'FR01', to_account: 'FR02', amount: 10 })
    expect(tx).toMatchObject({ id: 'tx1', status: 'created', fromAccount: 'FR01', toAccount: 'FR02' })
    const [url, init] = f.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toBe('/api/v1/transactions')
    expect(JSON.parse(init.body as string)).toEqual({ from_account: 'FR01', to_account: 'FR02', amount: 10 })
  })

  it('listTransactions : accepte { transactions: [...] }', async () => {
    const { api } = endpointsWith(() =>
      jsonResponse({
        transactions: [{ id: 'a', from_account: 'x', to_account: 'y', amount: '5.00', status: 'rejected', created_at: '2026-10-21T09:00:00Z' }],
      }),
    )
    const txs = await api.listTransactions()
    expect(txs).toHaveLength(1)
    expect(txs[0]).toMatchObject({ status: 'rejected', amount: 5, currency: 'EUR' })
  })
})

describe('parseurs', () => {
  it('rejette une réponse login sans jeton', () => {
    expect(() => parseLogin({})).toThrowError(/Jeton absent/)
  })
  it('rejette un compte sans solde numérique', () => {
    expect(() => parseAccounts([{ id: 'a', balance: 'abc' }])).toThrowError()
  })
  it('rejette une transaction sans created_at', () => {
    expect(() => parseTransaction({ id: '1', from_account: 'a', to_account: 'b', amount: 1 })).toThrowError()
  })
})

describe('decodeJwtExp', () => {
  it('lit le claim exp', () => {
    expect(decodeJwtExp(fakeJwt(1_800_000_000))).toBe(1_800_000_000)
  })
  it('renvoie null pour un jeton illisible', () => {
    expect(decodeJwtExp('pas-un-jwt')).toBeNull()
  })
})
