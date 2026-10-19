import { ApiError, errorFromResponse } from './errors'

export interface ApiClientOptions {
  baseUrl: string
  getToken: () => string | null
  /** Appelé sur un 401 d'une requête authentifiée (déconnexion). */
  onUnauthorized?: () => void
  fetchImpl?: typeof fetch
  timeoutMs?: number
}

export interface RequestOptions {
  method?: 'GET' | 'POST'
  body?: unknown
  /** false pour login (pas de Bearer, pas de déconnexion sur 401). */
  auth?: boolean
  signal?: AbortSignal
}

export interface ApiClient {
  request<T = unknown>(path: string, options?: RequestOptions): Promise<T>
}

/** Client HTTP centralisé : Bearer, JSON, erreurs normalisées du contrat, timeout. */
export function createApiClient(opts: ApiClientOptions): ApiClient {
  const { baseUrl, getToken, onUnauthorized, timeoutMs = 10_000 } = opts

  async function request<T = unknown>(path: string, o: RequestOptions = {}): Promise<T> {
    const { method = 'GET', body, auth = true, signal } = o
    const doFetch = opts.fetchImpl ?? fetch
    const headers: Record<string, string> = { Accept: 'application/json' }
    if (body !== undefined) headers['Content-Type'] = 'application/json'
    if (auth) {
      const token = getToken()
      if (token) headers.Authorization = `Bearer ${token}`
    }

    const controller = new AbortController()
    const onAbort = () => controller.abort()
    signal?.addEventListener('abort', onAbort)
    let timedOut = false
    const timer = setTimeout(() => {
      timedOut = true
      controller.abort()
    }, timeoutMs)

    let res: Response
    try {
      res = await doFetch(`${baseUrl}${path}`, {
        method,
        headers,
        body: body === undefined ? undefined : JSON.stringify(body),
        signal: controller.signal,
      })
    } catch (err) {
      if (signal?.aborted) throw err
      if (timedOut) throw new ApiError(0, 'timeout', 'Le serveur met trop de temps à répondre.')
      throw new ApiError(0, 'network_error', 'Impossible de joindre le serveur.')
    } finally {
      clearTimeout(timer)
      signal?.removeEventListener('abort', onAbort)
    }

    const parsed = await readJson(res)
    if (!res.ok) {
      const error = errorFromResponse(res.status, parsed)
      if (res.status === 401 && auth) onUnauthorized?.()
      throw error
    }
    return parsed as T
  }

  return { request }
}

async function readJson(res: Response): Promise<unknown> {
  if (res.status === 204) return null
  const text = await res.text()
  if (!text) return null
  try {
    return JSON.parse(text)
  } catch {
    return null
  }
}
