import { vi } from 'vitest'

export function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

/** Fabrique un JWT factice (non signé) avec le claim exp donné. */
export function fakeJwt(expSeconds: number): string {
  const b64 = (o: object) => btoa(JSON.stringify(o)).replace(/=+$/, '').replace(/\+/g, '-').replace(/\//g, '_')
  return `${b64({ alg: 'HS256', typ: 'JWT' })}.${b64({ sub: 'demo01', exp: expSeconds })}.sig`
}

export type Route = (init: RequestInit | undefined, url: string) => Response | Promise<Response>

/** Stub global fetch : routes "METHOD /path" -> réponse. */
export function stubFetch(routes: Record<string, Route>) {
  const fn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const key = `${init?.method ?? 'GET'} ${url.replace(/^https?:\/\/[^/]+/, '')}`
    const route = routes[key]
    if (!route) return jsonResponse({ error: { code: 'not_found', message: key } }, 404)
    return route(init, url)
  })
  vi.stubGlobal('fetch', fn)
  return fn
}

/** Simule la largeur d'écran : true = desktop (barre latérale), false = mobile (barre d'onglets). jsdom n'a pas matchMedia. */
export function setViewport(desktop: boolean) {
  vi.stubGlobal('matchMedia', (query: string) => ({
    matches: desktop,
    media: query,
    addEventListener: () => {},
    removeEventListener: () => {},
  }))
}
