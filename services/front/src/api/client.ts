import { ApiError, errorFromResponse } from './errors'

export interface ApiClientOptions {
  baseUrl: string
  getToken: () => string | null
  /** Appelé sur un 401 d'une requête authentifiée (déconnexion). */
  onUnauthorized?: () => void
  /**
   * Disponibilité observée : false sur réseau / timeout / 5xx, true sinon (bandeau d'état du service).
   * `startedAt` = performance.now() au départ de la requête.
   */
  onAvailability?: (up: boolean, startedAt: number) => void
  fetchImpl?: typeof fetch
  timeoutMs?: number
}

export interface RequestOptions {
  method?: 'GET' | 'POST' | 'PATCH' | 'DELETE'
  body?: unknown
  /** false pour login (pas de Bearer, pas de déconnexion sur 401). */
  auth?: boolean
  signal?: AbortSignal
  /**
   * false : une réponse saine ne vaut PAS reprise (seuls les échecs sont signalés). Pour les
   * sondes qui ne prouvent pas que les routes métier répondent (GET /api/v1/status, un 429 du WAF).
   */
  reportRecovery?: boolean
  /**
   * false : un 401 ne déconnecte pas (ré-authentification #51 : un mauvais mot de passe répond
   * 401 invalid_credentials, l'appelant décide).
   */
  logoutOnUnauthorized?: boolean
}

export interface DownloadedFile {
  blob: Blob
  /** Nom tiré de `Content-Disposition` (filename="…"), sinon null. */
  filename: string | null
}

export interface ApiClient {
  request<T = unknown>(path: string, options?: RequestOptions): Promise<T>
  /** Même client (Bearer, timeout, disponibilité, 401) mais corps lu en binaire : export CSV. */
  download(path: string, options?: RequestOptions): Promise<DownloadedFile>
}

/** Client HTTP centralisé : Bearer, JSON, erreurs normalisées du contrat, timeout. */
export function createApiClient(opts: ApiClientOptions): ApiClient {
  const { baseUrl, getToken, onUnauthorized, onAvailability, timeoutMs = 10_000 } = opts

  async function send(path: string, o: RequestOptions, accept: string): Promise<Response> {
    const { method = 'GET', body, auth = true, signal, reportRecovery = true, logoutOnUnauthorized = true } = o
    const doFetch = opts.fetchImpl ?? fetch
    const headers: Record<string, string> = { Accept: accept }
    if (body !== undefined) headers['Content-Type'] = 'application/json'
    if (auth) {
      const token = getToken()
      if (token) headers.Authorization = `Bearer ${token}`
    }

    const startedAt = performance.now()
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
      onAvailability?.(false, startedAt)
      if (timedOut) throw new ApiError(0, 'timeout', 'Le serveur met trop de temps à répondre.')
      throw new ApiError(0, 'network_error', 'Impossible de joindre le serveur.')
    } finally {
      clearTimeout(timer)
      signal?.removeEventListener('abort', onAbort)
    }

    if (res.status >= 500 || reportRecovery) onAvailability?.(res.status < 500, startedAt)
    if (!res.ok) {
      const error = errorFromResponse(res.status, await readJson(res))
      if (res.status === 401 && auth && logoutOnUnauthorized) onUnauthorized?.()
      throw error
    }
    return res
  }

  async function request<T = unknown>(path: string, o: RequestOptions = {}): Promise<T> {
    return (await readJson(await send(path, o, 'application/json'))) as T
  }

  async function download(path: string, o: RequestOptions = {}): Promise<DownloadedFile> {
    const res = await send(path, o, 'text/csv, application/json')
    const disposition = res.headers.get('Content-Disposition') ?? ''
    const m = /filename="?([^";]+)"?/i.exec(disposition)
    // Le corps (jusqu'à 5 000 lignes) est lu sous le même délai et la même normalisation
    // d'erreur que l'en-tête : jamais de bouton bloqué ni de TypeError brute.
    let timer: ReturnType<typeof setTimeout> | undefined
    const expiry = new Promise<never>((_, reject) => {
      timer = setTimeout(() => reject(new ApiError(0, 'timeout', 'Le serveur met trop de temps à répondre.')), timeoutMs)
    })
    try {
      return { blob: await Promise.race([res.blob(), expiry]), filename: m ? m[1]! : null }
    } catch (err) {
      onAvailability?.(false, performance.now())
      if (err instanceof ApiError) throw err
      throw new ApiError(0, 'network_error', 'Impossible de joindre le serveur.')
    } finally {
      clearTimeout(timer)
    }
  }

  return { request, download }
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
