import { FaceLandmarker, FilesetResolver } from '@mediapipe/tasks-vision'
import { rotationFromPoints } from '../lib/pose'
import type { DetectorFactory, Landmarks, PoseDetector } from './detector'

// Détecteur MediaPipe Face Landmarker, 100 % local : wasm (/mediapipe) et modèle
// (/models/face_landmarker.task) sont servis par le back-office lui-même
// (scripts/fetch-face-model.mjs), aucun CDN (CSP 'self' + 'wasm-unsafe-eval').

const WASM_BASE = '/mediapipe'
const MODEL_PATH = '/models/face_landmarker.task'

// Indices du maillage 478 points : 234 / 454 = bords du visage (côté gauche / droit de
// l'IMAGE), 1 / 4 = pointe du nez. Mêmes repères que face-id côté serveur.
const SIDE_L = 234
const SIDE_R = 454
const NOSE = [1, 4] as const

async function createLandmarker(delegate: 'GPU' | 'CPU'): Promise<FaceLandmarker> {
  const fileset = await FilesetResolver.forVisionTasks(WASM_BASE)
  return FaceLandmarker.createFromOptions(fileset, {
    baseOptions: { modelAssetPath: MODEL_PATH, delegate },
    runningMode: 'VIDEO',
    numFaces: 2,
  })
}

export const createMediaPipeDetector: DetectorFactory = async () => {
  // GPU d'abord (fluide) ; certains postes sans WebGL2 échouent : repli CPU.
  const landmarker = await createLandmarker('GPU').catch(() => createLandmarker('CPU'))
  let lastVideoTime = -1
  let lastTs = -1

  const detector: PoseDetector = {
    detect(video: HTMLVideoElement, ts: number): Landmarks | null {
      if (video.readyState < 2 || !video.videoWidth) return null
      // Pas de nouvelle image depuis la dernière trame : inutile de recalculer.
      if (video.currentTime === lastVideoTime) return null
      lastVideoTime = video.currentTime
      // MediaPipe exige des horodatages strictement croissants.
      const t = ts > lastTs ? ts : lastTs + 1
      lastTs = t
      const result = landmarker.detectForVideo(video, t)
      const faces = result.faceLandmarks.length
      const lm = result.faceLandmarks[0]
      if (!lm) return { points: [], rotation: null, faces: 0 }
      const l = lm[SIDE_L]
      const r = lm[SIDE_R]
      const noses = NOSE.map((i) => lm[i]?.x).filter((x): x is number => x !== undefined)
      // Coordonnées brutes (image NON miroir) : même formule que face-id sur le JPEG capturé.
      const rotation = l && r ? rotationFromPoints(l.x, r.x, noses) : null
      return { points: lm.map((p) => ({ x: p.x, y: p.y })), rotation, faces }
    },
    close() {
      landmarker.close()
    },
  }
  return detector
}
