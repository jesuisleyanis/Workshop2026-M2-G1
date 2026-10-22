import type { Pose } from '../../api/auth'

// Marges de CAPTURE propres au scanner (les seuils du contrat, 0.10 / 0.15 dans lib/pose.ts,
// restent le miroir exact du serveur et ne changent pas).
//
// Pourquoi : le client mesure le nez avec MediaPipe (points 1/4 = pointe saillante), le serveur
// avec dlib (nose_tip 31–35 = base des narines), qui se déplace moins quand la tête tourne :
// |rotation serveur| ≈ 0.8 × |rotation client|. Capturer dès 0.15 côté client donnerait ~0.12
// côté serveur, dans la zone morte => `wrong_pose`. On exige donc une pose plus franche avant
// de capturer : profil |r| >= 0.22 (≈ 0.18 serveur), face |r| <= 0.07 (≈ 0.06 serveur).
// À CALIBRER EN RECETTE sur la caméra du PC Hôte (rotation client vs rotation face-id).
export const CAPTURE_FACE_MAX = 0.07
export const CAPTURE_PROFILE_MIN = 0.22

/** La rotation (repère image non miroir) est-elle assez franche pour capturer `pose` ? */
export function meetsCapture(pose: Pose, rotation: number | null): boolean {
  if (rotation === null) return false
  if (pose === 'face') return Math.abs(rotation) <= CAPTURE_FACE_MAX
  if (pose === 'gauche') return rotation >= CAPTURE_PROFILE_MIN
  return rotation <= -CAPTURE_PROFILE_MIN
}
