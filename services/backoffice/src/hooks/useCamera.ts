import { useMemo, useRef, type RefObject } from 'react'

// Accès à la caméra USB DU PC HÔTE via getUserMedia (ADR 0005). Active uniquement pendant
// l'étape d'identification, coupée ensuite (vie privée + exigence consigne). La trame est
// encodée en JPEG base64 et envoyée à auth ; aucune image n'est conservée côté client.
//
// Le <video> appartient au composant (ref idiomatique) ; on le passe au hook.
export interface Camera {
  start: () => Promise<void>
  /** JPEG base64 (sans préfixe data:) de l'image BRUTE (non miroir), plus grand côté ≤ 640 px. */
  capture: () => string
  stop: () => void
  /** Élément <video> courant (lu à l'appel), pour le détecteur de pose. */
  readonly video: HTMLVideoElement | null
}

/** Plus grand côté de l'image envoyée : suffisant pour l'embedding, payload réduit. */
export const CAPTURE_MAX_SIDE = 640

export function useCamera(videoRef: RefObject<HTMLVideoElement | null>): Camera {
  const streamRef = useRef<MediaStream | null>(null)
  // Génération : chaque start()/stop() l'incrémente. Un getUserMedia qui se résout après un
  // stop() ou un start() plus récent (StrictMode, démontage rapide) est coupé aussitôt :
  // jamais de flux orphelin laissant la caméra allumée.
  const genRef = useRef(0)

  // API stable (créée une fois) : les refs ne sont lues qu'à l'appel, jamais pendant le rendu.
  return useMemo<Camera>(
    () => ({
      async start(): Promise<void> {
        const gen = ++genRef.current
        const s = await navigator.mediaDevices.getUserMedia({
          video: { facingMode: 'user', width: { ideal: 1280 }, height: { ideal: 720 } },
          audio: false,
        })
        if (gen !== genRef.current) {
          s.getTracks().forEach((track) => track.stop())
          return
        }
        streamRef.current?.getTracks().forEach((track) => track.stop())
        streamRef.current = s
        const video = videoRef.current
        if (video) {
          video.srcObject = s
          await video.play().catch(() => undefined)
        }
      },
      capture(): string {
        const video = videoRef.current
        // Échoue plutôt que d'émettre une image noire si la caméra n'a pas démarré (sinon un
        // problème matériel serait compté comme un échec d'authentification).
        if (!video || !streamRef.current) throw new Error('camera_not_ready')
        const vw = video.videoWidth || 320
        const vh = video.videoHeight || 240
        const scale = Math.min(1, CAPTURE_MAX_SIDE / Math.max(vw, vh))
        const canvas = document.createElement('canvas')
        canvas.width = Math.round(vw * scale)
        canvas.height = Math.round(vh * scale)
        const ctx = canvas.getContext('2d')
        // Image brute, NON miroir : l'aperçu est retourné en CSS seulement, le serveur calcule
        // la pose sur cette image avec la même formule que le détecteur client.
        if (ctx) ctx.drawImage(video, 0, 0, canvas.width, canvas.height)
        const dataUrl = canvas.toDataURL('image/jpeg', 0.8)
        return dataUrl.split(',')[1] ?? '' // base64 sans le préfixe "data:..."
      },
      stop(): void {
        genRef.current++
        streamRef.current?.getTracks().forEach((track) => track.stop())
        streamRef.current = null
        const video = videoRef.current
        if (video) video.srcObject = null
      },
      get video(): HTMLVideoElement | null {
        return videoRef.current
      },
    }),
    [videoRef],
  )
}
