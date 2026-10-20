// Libellés français des erreurs des API d'administration / d'initialisation.
import { ApiError, type EnrollmentDetail } from '../api/http'
import type { Pose } from '../api/auth'

export const POSE_LABELS: Record<Pose, string> = { face: 'Face', gauche: 'Gauche', droite: 'Droite' }

const REJECTION_REASONS: Record<string, string> = {
  wrong_pose: 'pose incorrecte',
  no_face: 'aucun visage',
  multiple_faces: 'plusieurs visages',
  inconsistent: 'pas la même personne',
  invalid_image: 'image illisible',
}

export const reasonLabel = (reason: string): string => REJECTION_REASONS[reason] ?? reason
export const poseLabel = (pose: string): string => POSE_LABELS[pose as Pose] ?? pose

/** Détails d'un rejet d'enrôlement (422), ou null si l'erreur n'en est pas un. */
export function enrollmentRejection(err: unknown): EnrollmentDetail[] | null {
  if (err instanceof ApiError && err.status === 422 && err.code === 'enrollment_rejected') return err.details ?? []
  return null
}

export function adminErrorText(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 0) return 'Service injoignable.'
    if (err.code === 'last_admin') return 'Action refusée : il doit rester au moins un administrateur enrôlé.'
    if (err.code === 'username_taken') return 'Cet identifiant est déjà utilisé.'
    if (err.code === 'not_enrolled') return 'Ce compte n’a pas de visage enrôlé.'
    if (err.code === 'bootstrap_denied') return 'Jeton d’initialisation invalide ou initialisation déjà effectuée.'
    if (err.status === 401) return 'Session expirée. Reconnectez-vous.'
    if (err.status === 403) return 'Droits insuffisants pour cette action.'
    if (err.status === 404) return 'Compte introuvable.'
    if (err.status === 503) return 'Service de reconnaissance indisponible. Réessayez plus tard.'
  }
  return 'Échec de la demande. Réessayez.'
}
