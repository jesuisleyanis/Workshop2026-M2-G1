// Contrat du détecteur de pose utilisé par le FaceScanner. L'implémentation réelle
// (MediaPipe, ./mediapipe.ts) est chargée à la demande ; les tests injectent un faux détecteur.

export interface Landmarks {
  /** Points du maillage du 1er visage, normalisés 0..1, repère image NON miroir. */
  points: { x: number; y: number }[]
  /** Rotation de la tête (cf. lib/pose.ts) ; > 0 = tête tournée vers la gauche de la personne. */
  rotation: number | null
  /** Nombre de visages détectés. */
  faces: number
}

export interface PoseDetector {
  /** null si aucune nouvelle trame exploitable (vidéo pas prête, trame identique). */
  detect(video: HTMLVideoElement, ts: number): Landmarks | null
  close(): void
}

export type DetectorFactory = () => Promise<PoseDetector>

/**
 * Fabrique par défaut : import dynamique de MediaPipe (chunk séparé) pour que le premier
 * affichage et les tests n'embarquent ni le bundle ni le wasm.
 */
export const loadMediaPipeDetector: DetectorFactory = async () => {
  const { createMediaPipeDetector } = await import('./mediapipe')
  return createMediaPipeDetector()
}
