import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  AuthError,
  bootstrap,
  bootstrapStatus,
  deviceStatus,
  identify,
  submitPassword,
  verifyFace,
} from './auth'
import { ApiError } from './http'

function fakeResponse(opts: {
  ok: boolean
  status: number
  body?: unknown
  headers?: Record<string, string>
}): Response {
  return {
    ok: opts.ok,
    status: opts.status,
    json: async () => opts.body,
    headers: { get: (k: string) => opts.headers?.[k] ?? null },
  } as unknown as Response
}

function stubFetch(resp: Response) {
  const fetchMock = vi.fn().mockResolvedValue(resp)
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

function lastCall(fetchMock: ReturnType<typeof vi.fn>) {
  const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit]
  return { url, init, body: init.body ? JSON.parse(init.body as string) : undefined }
}

afterEach(() => vi.restoreAllMocks())

describe("client de l'API auth à étapes", () => {
  it('identify poste le username et renvoie le challenge avec les poses', async () => {
    const fetchMock = stubFetch(
      fakeResponse({
        ok: true,
        status: 200,
        body: { challenge_id: 'c1', step: 'face', expires_in: 60, camera: true, poses: ['face', 'gauche', 'droite'] },
      }),
    )
    const res = await identify('op01')
    expect(res.challenge_id).toBe('c1')
    expect(res.poses).toEqual(['face', 'gauche', 'droite'])
    const { url, init, body } = lastCall(fetchMock)
    expect(url).toBe('/api/v1/auth/identify')
    expect(init.method).toBe('POST')
    expect(body).toEqual({ username: 'op01' })
  })

  it('traduit un 429 en ApiError avec retryAfter', async () => {
    stubFetch(
      fakeResponse({
        ok: false,
        status: 429,
        body: { error: { code: 'locked_out', message: 'Too many' } },
        headers: { 'Retry-After': '300' },
      }),
    )
    await expect(identify('op01')).rejects.toMatchObject({ status: 429, code: 'locked_out', retryAfter: 300 })
  })

  it('verifyFace poste les 3 frames {pose,image_b64}', async () => {
    const fetchMock = stubFetch(
      fakeResponse({ ok: true, status: 200, body: { recognized: true, step: 'password', attempts_left: 2, cooldown: 0 } }),
    )
    const frames = [
      { pose: 'face' as const, image_b64: 'A' },
      { pose: 'gauche' as const, image_b64: 'B' },
      { pose: 'droite' as const, image_b64: 'C' },
    ]
    const res = await verifyFace('c1', frames)
    expect(res.recognized).toBe(true)
    const { url, body } = lastCall(fetchMock)
    expect(url).toBe('/api/v1/auth/face')
    expect(body).toEqual({ challenge_id: 'c1', frames })
  })

  it('submitPassword expose le Retry-After du 401 et le code du 403', async () => {
    stubFetch(
      fakeResponse({
        ok: false,
        status: 401,
        body: { error: { code: 'invalid_credentials', message: 'x' } },
        headers: { 'Retry-After': '3' },
      }),
    )
    await expect(submitPassword('c1', 'pw')).rejects.toMatchObject({
      status: 401,
      code: 'invalid_credentials',
      retryAfter: 3,
    })
    stubFetch(fakeResponse({ ok: false, status: 403, body: { error: { code: 'role_not_authorized', message: 'x' } } }))
    await expect(submitPassword('c1', 'pw')).rejects.toHaveProperty('code', 'role_not_authorized')
  })

  it('transforme une panne réseau en ApiError (alias AuthError)', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('down')))
    const err = await verifyFace('c1', []).catch((e) => e)
    expect(err).toBeInstanceOf(AuthError)
    expect(err).toBeInstanceOf(ApiError)
    expect(err.code).toBe('network_error')
    expect(err.status).toBe(0)
  })

  it('deviceStatus lit led_online en GET sans corps', async () => {
    const fetchMock = stubFetch(fakeResponse({ ok: true, status: 200, body: { led_online: null } }))
    expect(await deviceStatus()).toEqual({ led_online: null })
    const { url, init } = lastCall(fetchMock)
    expect(url).toBe('/api/v1/auth/device')
    expect(init.method).toBe('GET')
    expect(init.body).toBeUndefined()
  })

  it('bootstrapStatus lit required', async () => {
    const fetchMock = stubFetch(fakeResponse({ ok: true, status: 200, body: { required: true } }))
    expect(await bootstrapStatus()).toEqual({ required: true })
    expect(lastCall(fetchMock).url).toBe('/api/v1/auth/bootstrap')
  })

  it('bootstrap poste token, identifiants et poses ; remonte les details du 422', async () => {
    const payload = {
      token: 'tok',
      username: 'root',
      password: 'pw',
      poses: { face: 'A', gauche: 'B', droite: 'C' },
    }
    const fetchMock = stubFetch(fakeResponse({ ok: true, status: 201, body: { username: 'root', role: 'admin' } }))
    expect(await bootstrap(payload)).toEqual({ username: 'root', role: 'admin' })
    const { init, body } = lastCall(fetchMock)
    expect(init.method).toBe('POST')
    expect(body).toEqual(payload)

    const details = [{ pose: 'gauche', reason: 'no_face' }]
    stubFetch(
      fakeResponse({
        ok: false,
        status: 422,
        body: { error: { code: 'enrollment_rejected', message: 'x', details } },
      }),
    )
    await expect(bootstrap(payload)).rejects.toMatchObject({ status: 422, code: 'enrollment_rejected', details })
  })
})
