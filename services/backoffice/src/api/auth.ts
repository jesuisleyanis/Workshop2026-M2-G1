// Client de l'API d'authentification à étapes du back-office (contrat §5.2).
import { API_BASE } from '../config'

export type Step = 'face' | 'password'

export interface IdentifyResult {
  challenge_id: string
  step: Step
  expires_in: number
  camera: boolean
}
export interface FaceResult {
  recognized: boolean
  step: Step
  attempts_left: number
}
export interface TokenResult {
  access_token: string
  token_type: string
  expires_in: number
  role: string
}

export class AuthError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly retryAfter?: number,
  ) {
    super(message)
    this.name = 'AuthError'
  }
}

async function post<T>(path: string, body: unknown): Promise<T> {
  let resp: Response
  try {
    resp = await fetch(`${API_BASE}${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
  } catch {
    throw new AuthError(0, 'network_error', 'Service injoignable')
  }
  if (resp.ok) return (await resp.json()) as T
  let code = `http_${resp.status}`
  let message = 'Erreur'
  try {
    const err = (await resp.json())?.error
    if (err?.code) code = err.code
    if (err?.message) message = err.message
  } catch {
    /* corps non-JSON : on garde les valeurs par défaut */
  }
  const retryHeader = resp.headers.get('Retry-After')
  throw new AuthError(resp.status, code, message, retryHeader ? Number(retryHeader) : undefined)
}

export const identify = (username: string) =>
  post<IdentifyResult>('/api/v1/auth/identify', { username })

export const verifyFace = (challenge_id: string, image_b64: string) =>
  post<FaceResult>('/api/v1/auth/face', { challenge_id, image_b64 })

export const submitPassword = (challenge_id: string, password: string) =>
  post<TokenResult>('/api/v1/auth/password', { challenge_id, password })
