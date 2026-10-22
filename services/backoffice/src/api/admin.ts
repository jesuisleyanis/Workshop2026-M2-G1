// Client de l'API d'administration des habilitations (jeton Bearer d'un admin).
import type { Pose } from './auth'
import { request } from './http'

export type AgentRole = 'customer' | 'operator' | 'admin'

export interface AgentRow {
  username: string
  role: AgentRole
  /** Enrôlement UTILISABLE (vérifiable par le modèle chargé de face-id). */
  enrolled: boolean
  /** Ligne d'enrôlement présente mais périmée (changement de modèle, ligne v1) : réenrôlement requis. */
  stale?: boolean
  enrolled_at: string | null
  enrolled_by: string | null
}

const userPath = (username: string) => `/api/v1/admin/users/${encodeURIComponent(username)}`

export const listUsers = (token: string) => request<AgentRow[]>('/api/v1/admin/users', { token })

export const createUser = (token: string, body: { username: string; password: string; role: AgentRole }) =>
  request<{ username: string; role: AgentRole }>('/api/v1/admin/users', { method: 'POST', body, token })

export const setRole = (token: string, username: string, role: AgentRole) =>
  request<{ username: string; role: AgentRole }>(userPath(username), { method: 'PATCH', body: { role }, token })

export const enrollFace = (token: string, username: string, poses: Record<Pose, string>) =>
  request<{ enrolled: boolean; model_version: string | null }>(`${userPath(username)}/face`, {
    method: 'PUT',
    body: { poses },
    token,
  })

export const revokeFace = (token: string, username: string) =>
  request<void>(`${userPath(username)}/face`, { method: 'DELETE', token })

export const facePhotos = (token: string, username: string) =>
  request<{ photos: Record<Pose, string> }>(`${userPath(username)}/face/photos`, { token })
