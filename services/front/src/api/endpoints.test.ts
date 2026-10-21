import { describe, expect, it, vi } from 'vitest'
import { createApiClient } from './client'
import { createEndpoints } from './index'
import { decodeJwtClaims, decodeJwtExp } from './tokenStore'
import { parseAccounts, parseLimits, parseLogin, parseTransaction } from './parsers'
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

  it('bénéficiaires : GET, POST {display_name, iban_fake}, DELETE /{id} (204)', async () => {
    const row = { id: 5, display_name: 'Léa', account_id: 42, iban_fake: 'FR76 9001', created_at: '2026-10-21T10:00:00Z' }
    const { api, f } = endpointsWith((_u, init) =>
      init?.method === 'DELETE' ? new Response(null, { status: 204 }) : jsonResponse(init?.method === 'POST' ? row : [row]),
    )
    expect(await api.listBeneficiaries()).toEqual([{ id: '5', name: 'Léa', accountId: '42', iban: 'FR76 9001', createdAt: '2026-10-21T10:00:00Z' }])
    await api.addBeneficiary({ name: 'Léa', iban: 'FR76 9001' })
    expect(JSON.parse((f.mock.calls[1]![1] as RequestInit).body as string)).toEqual({ display_name: 'Léa', iban_fake: 'FR76 9001' })
    await expect(api.deleteBeneficiary('5')).resolves.toBeUndefined()
    expect(f.mock.calls[2]).toEqual(['/api/v1/beneficiaries/5', expect.objectContaining({ method: 'DELETE' })])
  })

  it('transactions : catégorie absente => « transfer », inconnue => « other », masquée (reçu) => null', () => {
    const base = { id: 1, src_account: 1, dst_account: 2, amount_cents: 100, status: 'created' }
    expect(parseTransaction(base).category).toBe('transfer')
    expect(parseTransaction({ ...base, category: 'casino' }).category).toBe('other')
    expect(parseTransaction({ ...base, category: null }).category).toBeNull()
    expect(parseTransaction({ ...base, category: 'health' }).category).toBe('health')
  })

  it('createTransaction : category envoyée seulement si fournie', async () => {
    const { api, f } = endpointsWith(() => jsonResponse({ id: 1, src_account: 1, dst_account: 2, amount_cents: 100, status: 'created' }, 201))
    await api.createTransaction({ from_account: '1', to_account: '2', amount: 1, category: 'food' })
    await api.createTransaction({ from_account: '1', to_account: '2', amount: 1 })
    const bodies = f.mock.calls.map((c) => JSON.parse((c[1] as RequestInit).body as string))
    expect(bodies[0]).toEqual({ src_account: 1, dst_account: 2, amount_cents: 100, category: 'food' })
    expect(bodies[1]).not.toHaveProperty('category')
  })

  it('getSpending : GET /api/v1/stats/spending?period=, centimes -> euros', async () => {
    const { api, f } = endpointsWith(() =>
      jsonResponse({
        period: 'week',
        offset: -1,
        start: '2026-10-19',
        end: '2026-10-26',
        total_cents: 1250,
        by_category: [{ category: 'food', amount_cents: 1250, share: 1 }],
        by_day: [{ date: '2026-10-19', amount_cents: 1250 }],
      }),
    )
    expect(await api.getSpending('week', -1)).toEqual({
      period: 'week',
      offset: -1,
      start: '2026-10-19',
      end: '2026-10-26',
      total: 12.5,
      byCategory: [{ category: 'food', amount: 12.5, share: 1 }],
      byDay: [{ date: '2026-10-19', amount: 12.5 }],
    })
    expect((f.mock.calls[0] as unknown as [string])[0]).toBe('/api/v1/stats/spending?period=week&offset=-1')
  })

  it('plafonds : centimes -> euros, null (sans plafond) préservé', () => {
    expect(
      parseLimits([
        { account_id: 1, monthly_limit_cents: 200000, used_cents: 1050, remaining_cents: 198950, period_end: '2026-11-01' },
        { account_id: 2, monthly_limit_cents: null, used_cents: 0, remaining_cents: null, period_end: '2026-11-01' },
      ]),
    ).toEqual([
      { accountId: '1', limit: 2000, used: 10.5, remaining: 1989.5, periodEnd: '2026-11-01' },
      { accountId: '2', limit: null, used: 0, remaining: null, periodEnd: '2026-11-01' },
    ])
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
