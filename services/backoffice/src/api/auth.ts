// Client de l'API d'authentification à étapes du back-office (identifiant -> visage -> mot de passe).
import { ApiError, request } from './http'

export type Pose = 'face' | 'gauche' | 'droite'
export type Step = 'face' | 'password'

export interface IdentifyResult {
  challenge_id: string
  step: Step
  expires_in: number
  camera: boolean
  /** Trois poses à capturer dans l'ordre demandé, ou [] si l'étape visage est sautée. */
  poses: Pose[]
}
export interface FaceFrame {
  pose: Pose
  image_b64: string
}
export interface FaceResult {
  recognized: boolean
  step: 'password' | 'identify'
  attempts_left: number
  cooldown: number
}
export interface TokenResult {
  access_token: string
  token_type: string
  expires_in: number
  role: string
}

export { ApiError as AuthError }

export const identify = (username: string) =>
  request<IdentifyResult>('/api/v1/auth/identify', { method: 'POST', body: { username } })

export const verifyFace = (challenge_id: string, frames: FaceFrame[]) =>
  request<FaceResult>('/api/v1/auth/face', { method: 'POST', body: { challenge_id, frames } })

export const submitPassword = (challenge_id: string, password: string) =>
  request<TokenResult>('/api/v1/auth/password', { method: 'POST', body: { challenge_id, password } })

export const deviceStatus = () => request<{ led_online: boolean | null }>('/api/v1/auth/device')

export const bootstrapStatus = () => request<{ required: boolean }>('/api/v1/auth/bootstrap')

export const bootstrap = (body: {
  token: string
  username: string
  password: string
  poses: Record<Pose, string>
}) => request<{ username: string; role: 'admin' }>('/api/v1/auth/bootstrap', { method: 'POST', body })
