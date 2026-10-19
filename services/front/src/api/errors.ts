import type { ApiErrorBody } from '../types/api'

/** Erreur d'API normalisée (contrat : error.code / message / request_id). */
export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly requestId: string | null

  constructor(status: number, code: string, message: string, requestId: string | null = null) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.requestId = requestId
  }

  get isUnauthorized(): boolean {
    return this.status === 401
  }
  get isRateLimited(): boolean {
    return this.status === 429
  }
  get isNetwork(): boolean {
    return this.code === 'network_error' || this.code === 'timeout'
  }
}

function isErrorBody(v: unknown): v is ApiErrorBody {
  if (typeof v !== 'object' || v === null || !('error' in v)) return false
  const e = (v as { error: unknown }).error
  return typeof e === 'object' && e !== null && typeof (e as { code?: unknown }).code === 'string'
}

/** Construit une ApiError depuis une réponse HTTP non-2xx (corps JSON du contrat ou repli générique). */
export function errorFromResponse(status: number, body: unknown): ApiError {
  if (isErrorBody(body)) {
    const { code, message, request_id } = body.error
    return new ApiError(status, code, typeof message === 'string' ? message : code, request_id ?? null)
  }
  return new ApiError(status, `http_${status}`, defaultMessage(status))
}

function defaultMessage(status: number): string {
  if (status === 401) return 'Session expirée ou identifiants invalides.'
  if (status === 403) return 'Accès refusé.'
  if (status === 429) return 'Trop de requêtes. Réessayez dans un instant.'
  if (status >= 500) return 'Service momentanément indisponible.'
  return `Erreur inattendue (HTTP ${status}).`
}
