// Logique de pose (face / gauche / droite) — miroir exact de services/face-id/src/face_id/poses.py.
import type { Pose } from '../api/auth'

/** |rotation| <= SEUIL_FACE => « face ». */
export const SEUIL_FACE = 0.1
/** rotation >= SEUIL_PROFIL => « gauche » ; rotation <= -SEUIL_PROFIL => « droite ». */
export const SEUIL_PROFIL = 0.15

export const POSE_LABELS: Record<Pose, string> = {
  face: 'Face',
  gauche: 'Profil gauche',
  droite: 'Profil droit',
}

/** Rotation = (moyenne x du nez − x mâchoire gauche) / largeur mâchoire − 0.5 ; null si indéterminée. */
export function rotationFromPoints(jawLeftX: number, jawRightX: number, noseXs: number[]): number | null {
  const width = jawRightX - jawLeftX
  if (width <= 0 || noseXs.length === 0) return null
  const mean = noseXs.reduce((a, b) => a + b, 0) / noseXs.length
  return (mean - jawLeftX) / width - 0.5
}

/** Classe une rotation en pose ; null dans la zone morte (entre les deux seuils). */
export function poseFromRotation(r: number | null): Pose | null {
  if (r === null) return null
  if (Math.abs(r) <= SEUIL_FACE) return 'face'
  if (r >= SEUIL_PROFIL) return 'gauche'
  if (r <= -SEUIL_PROFIL) return 'droite'
  return null
}
