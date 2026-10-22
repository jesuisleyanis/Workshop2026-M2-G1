import { afterEach, describe, expect, it, vi } from 'vitest'
import { createUser, enrollFace, facePhotos, listUsers, revokeFace, setRole } from './admin'

function fakeResponse(status: number, body?: unknown, headers: Record<string, string> = {}): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => {
      if (body === undefined) throw new Error('no body')
      return body
    },
    headers: { get: (k: string) => headers[k] ?? null },
  } as unknown as Response
}

function stubFetch(resp: Response) {
  const fetchMock = vi.fn().mockResolvedValue(resp)
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

function call(fetchMock: ReturnType<typeof vi.fn>) {
  const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit]
  const headers = init.headers as Record<string, string>
  return { url, init, headers, body: init.body ? JSON.parse(init.body as string) : undefined }
}

afterEach(() => vi.restoreAllMocks())

describe("client de l'API d'administration", () => {
  it('listUsers envoie le Bearer et renvoie les agents', async () => {
    const rows = [{ username: 'a', role: 'admin', enrolled: true, enrolled_at: 't', enrolled_by: 'b' }]
    const f = stubFetch(fakeResponse(200, rows))
    expect(await listUsers('TOK')).toEqual(rows)
    const { url, init, headers } = call(f)
    expect(url).toBe('/api/v1/admin/users')
    expect(init.method).toBe('GET')
    expect(headers.Authorization).toBe('Bearer TOK')
  })

  it('createUser poste username/password/role', async () => {
    const f = stubFetch(fakeResponse(201, { username: 'op', role: 'operator' }))
    await createUser('TOK', { username: 'op', password: 'pw', role: 'operator' })
    const { url, init, body } = call(f)
    expect(url).toBe('/api/v1/admin/users')
    expect(init.method).toBe('POST')
    expect(body).toEqual({ username: 'op', password: 'pw', role: 'operator' })
  })

  it('createUser remonte username_taken (409)', async () => {
    stubFetch(fakeResponse(409, { error: { code: 'username_taken', message: 'x' } }))
    await expect(createUser('TOK', { username: 'op', password: 'pw', role: 'operator' })).rejects.toMatchObject({
      status: 409,
      code: 'username_taken',
    })
  })

  it("setRole fait un PATCH sur l'utilisateur encodé", async () => {
    const f = stubFetch(fakeResponse(200, { username: 'a b', role: 'admin' }))
    await setRole('TOK', 'a b', 'admin')
    const { url, init, body } = call(f)
    expect(url).toBe('/api/v1/admin/users/a%20b')
    expect(init.method).toBe('PATCH')
    expect(body).toEqual({ role: 'admin' })
  })

  it('setRole remonte last_admin (409)', async () => {
    stubFetch(fakeResponse(409, { error: { code: 'last_admin', message: 'x' } }))
    await expect(setRole('TOK', 'a', 'operator')).rejects.toHaveProperty('code', 'last_admin')
  })

  it('enrollFace fait un PUT des poses sur /face', async () => {
    const f = stubFetch(fakeResponse(200, { enrolled: true, model_version: 'team-dlib-1.3.0' }))
    const poses = { face: 'A', gauche: 'B', droite: 'C' }
    expect(await enrollFace('TOK', 'op', poses)).toEqual({ enrolled: true, model_version: 'team-dlib-1.3.0' })
    const { url, init, body } = call(f)
    expect(url).toBe('/api/v1/admin/users/op/face')
    expect(init.method).toBe('PUT')
    expect(body).toEqual({ poses })
  })

  it("enrollFace remonte les details d'un 422", async () => {
    const details = [{ pose: 'face', reason: 'no_face' }]
    stubFetch(fakeResponse(422, { error: { code: 'enrollment_rejected', message: 'x', details } }))
    await expect(enrollFace('TOK', 'op', { face: 'A', gauche: 'B', droite: 'C' })).rejects.toMatchObject({
      status: 422,
      details,
    })
  })

  it('revokeFace fait un DELETE et tolère le 204 sans corps', async () => {
    const f = stubFetch(fakeResponse(204))
    await expect(revokeFace('TOK', 'op')).resolves.toBeUndefined()
    const { url, init, headers } = call(f)
    expect(url).toBe('/api/v1/admin/users/op/face')
    expect(init.method).toBe('DELETE')
    expect(init.body).toBeUndefined()
    expect(headers.Authorization).toBe('Bearer TOK')
  })

  it('facePhotos renvoie les trois photos', async () => {
    const photos = { face: 'A', gauche: 'B', droite: 'C' }
    const f = stubFetch(fakeResponse(200, { photos }))
    expect(await facePhotos('TOK', 'op')).toEqual({ photos })
    expect(call(f).url).toBe('/api/v1/admin/users/op/face/photos')
  })
})
