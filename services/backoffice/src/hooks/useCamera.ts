import { useMemo, useRef, type RefObject } from 'react'

// Accès à la caméra USB DU PC HÔTE via getUserMedia (ADR 0005). Active uniquement pendant
// l'étape d'identification, coupée ensuite (vie privée + exigence consigne). La trame est
// encodée en JPEG base64 et envoyée à auth ; aucune image n'est conservée côté client.
//
// Le <video> appartient au composant (ref idiomatique) ; on le passe au hook.
export interface Camera {
  start: () => Promise<void>
  capture: () => string
  stop: () => void
}

export function useCamera(videoRef: RefObject<HTMLVideoElement | null>): Camera {
  const streamRef = useRef<MediaStream | null>(null)
  const stoppedRef = useRef(false)

  // API stable (créée une fois) : les refs ne sont lues qu'à l'appel, jamais pendant le rendu.
  return useMemo<Camera>(
    () => ({
      async start(): Promise<void> {
        stoppedRef.current = false
        const s = await navigator.mediaDevices.getUserMedia({
          video: { facingMode: 'user' },
          audio: false,
        })
        // Si stop() est survenu pendant l'attente (démontage / changement de phase), on coupe
        // immédiatement et on ne garde pas la référence : pas de caméra restée allumée.
        if (stoppedRef.current) {
          s.getTracks().forEach((track) => track.stop())
          return
        }
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
        const canvas = document.createElement('canvas')
        canvas.width = video.videoWidth || 320
        canvas.height = video.videoHeight || 240
        const ctx = canvas.getContext('2d')
        if (ctx) ctx.drawImage(video, 0, 0, canvas.width, canvas.height)
        const dataUrl = canvas.toDataURL('image/jpeg', 0.8)
        return dataUrl.split(',')[1] ?? '' // base64 sans le préfixe "data:..."
      },
      stop(): void {
        stoppedRef.current = true
        streamRef.current?.getTracks().forEach((track) => track.stop())
        streamRef.current = null
        const video = videoRef.current
        if (video) video.srcObject = null
      },
    }),
    [videoRef],
  )
}
