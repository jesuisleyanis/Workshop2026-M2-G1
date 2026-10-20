import { afterEach, describe, expect, it, vi } from 'vitest'
import { AuthError, identify, submitPassword, verifyFace } from './auth'

function fakeResponse(opts: {
  ok: boolean
  status: number
  body: unknown
  headers?: Record<string, string>
}): Response {
  return {
    ok: opts.ok,
    status: opts.status,
    json: async () => opts.body,
    headers: { get: (k: string) => opts.headers?.[k] ?? null },
  } as unknown as Response
}

afterEach(() => vi.restoreAllMocks())

describe("client de l'API auth à étapes", () => {
  it('identify poste le username et renvoie le challenge', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(
        fakeResponse({ ok: true, status: 200, body: { challenge_id: 'c1', step: 'face', expires_in: 60, camera: true } }),
      )
    vi.stubGlobal('fetch', fetchMock)
    const res = await identify('op01')
    expect(res.challenge_id).toBe('c1')
    const init = fetchMock.mock.calls[0]?.[1] as RequestInit
    expect(JSON.parse(init.body as string)).toEqual({ username: 'op01' })
  })

  it('traduit un 429 en AuthError avec retryAfter', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        fakeResponse({
          ok: false,
          status: 429,
          body: { error: { code: 'locked_out', message: 'Too many' } },
          headers: { 'Retry-After': '300' },
        }),
      ),
    )
    await expect(identify('op01')).rejects.toMatchObject({
      status: 429,
      code: 'locked_out',
      retryAfter: 300,
    })
  })

  it('expose le code métier sur un 403', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        fakeResponse({ ok: false, status: 403, body: { error: { code: 'role_not_authorized', message: 'x' } } }),
      ),
    )
    await expect(submitPassword('c1', 'pw')).rejects.toHaveProperty('code', 'role_not_authorized')
  })

  it('transforme une panne réseau en AuthError', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('down')))
    const err = await verifyFace('c1', 'img').catch((e) => e)
    expect(err).toBeInstanceOf(AuthError)
    expect(err.code).toBe('network_error')
  })
})
