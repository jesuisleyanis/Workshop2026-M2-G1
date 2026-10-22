// Client HTTP commun du back-office : erreurs typées (contrat {"error":{code,message,...}}).
import { API_BASE } from '../config'

export interface EnrollmentDetail {
  pose: string
  reason: string
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly retryAfter?: number,
    readonly details?: EnrollmentDetail[],
    readonly requestId?: string,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

export interface RequestInitLite {
  method?: string
  body?: unknown
  /** Jeton Bearer (routes d'administration). */
  token?: string
}

export async function request<T>(path: string, init: RequestInitLite = {}): Promise<T> {
  const headers: Record<string, string> = {}
  if (init.body !== undefined) headers['Content-Type'] = 'application/json'
  if (init.token) headers.Authorization = `Bearer ${init.token}`

  let resp: Response
  try {
    resp = await fetch(`${API_BASE}${path}`, {
      method: init.method ?? 'GET',
      headers,
      body: init.body !== undefined ? JSON.stringify(init.body) : undefined,
    })
  } catch {
    throw new ApiError(0, 'network_error', 'Service injoignable')
  }

  if (resp.ok) {
    if (resp.status === 204) return undefined as T
    return (await resp.json()) as T
  }

  let code = `http_${resp.status}`
  let message = 'Erreur'
  let details: EnrollmentDetail[] | undefined
  let requestId: string | undefined
  try {
    const err = (await resp.json())?.error
    if (err?.code) code = err.code
    if (err?.message) message = err.message
    if (Array.isArray(err?.details)) details = err.details
    if (err?.request_id) requestId = err.request_id
  } catch {
    /* corps non-JSON : on garde les valeurs par défaut */
  }
  const retryHeader = resp.headers.get('Retry-After')
  const retryAfter = retryHeader && Number.isFinite(Number(retryHeader)) ? Number(retryHeader) : undefined
  throw new ApiError(resp.status, code, message, retryAfter, details, requestId)
}
