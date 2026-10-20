import { useCallback, useEffect, useRef, useState, type ReactNode, type RefObject } from 'react'
import type { FaceFrame, Pose } from '../../api/auth'
import type { Camera } from '../../hooks/useCamera'
import { loadMediaPipeDetector, type DetectorFactory, type Landmarks, type PoseDetector } from '../../vision/detector'
import { HudOverlay, VerdictOverlay, YawGauge, formatRotation, type Direction, type Engine, type LiveReading, type Verdict } from './HudOverlay'
import { meetsCapture } from './captureMargins'
import { useHoldTimer } from './useHoldTimer'
import './scanner.css'

// Étape de scan du visage (login et enrôlement). Démarre la caméra au montage, suit la pose en
// continu (MediaPipe, chargé à la demande) et capture automatiquement chaque pose demandée après
// un maintien de `holdMs`. Repli manuel (bouton + 3-2-1) si le détecteur ne charge pas.
// Le verdict est piloté par le parent ; pour relancer un scan, le parent change la `key`.
//
// ORIENTATION (à ne pas inverser) :
//  - Les poses sont définies sur l'image NON miroir, celle qui part au serveur : face-id
//    calcule la rotation sur le JPEG brut avec la même formule (lib/pose.ts). On calcule donc
//    la rotation sur les landmarks bruts, jamais sur l'aperçu.
//  - rotation > 0 = nez vers les x croissants de l'image brute = la personne tourne la tête
//    vers SA gauche (la caméra lui fait face : sa gauche est à droite de l'image brute).
//  - L'aperçu est affiché en miroir (comme un miroir de salle de bain) : la gauche de la
//    personne apparaît à GAUCHE de l'écran. La consigne « gauche » pointe donc vers la gauche
//    de l'écran (←), « droite » vers la droite (→). Flèches et jauge sont hors couche miroir.

export interface FaceScannerProps {
  mode: 'verify' | 'enroll'
  /** Ordre des poses à capturer. */
  poses: Pose[]
  /** Hook useCamera (start/stop/capture). */
  camera: Camera
  /** Ref passée à useCamera : le scanner rend le <video> correspondant. */
  videoRef: RefObject<HTMLVideoElement | null>
  /** Défaut : MediaPipe chargé à la demande ; tests : faux détecteur. */
  detectorFactory?: DetectorFactory
  /** Durée de maintien de la pose avant capture (ms). */
  holdMs?: number
  /** Piloté par le parent ; `analyzing` est aussi affiché d'office après la dernière capture. */
  verdict?: Verdict
  onComplete: (frames: FaceFrame[]) => void
  onCancel?: () => void
  /** Caméra inaccessible (getUserMedia refusé / absent). */
  onCameraError?: () => void
  /** Texte court affiché dans le HUD (ex. « TENTATIVE 2/3 »). */
  statusText?: string
  /** Contenu du parent rendu en pied de cadre (ex. décompte de refroidissement). */
  children?: ReactNode
}

/** Au-delà, le détecteur est considéré indisponible : mode manuel. */
export const DETECTOR_TIMEOUT_MS = 10_000
/** Pause après une capture : laisse le flash et le changement de consigne se lire. */
export const STEP_PAUSE_MS = 400
const COUNTDOWN_FROM = 3

const ACCENT = '#5eead4'
const MESH_COLORS: Record<Verdict, string> = { idle: ACCENT, analyzing: ACCENT, granted: '#22c55e', denied: '#ef4444' }

const DIRECTIONS: Record<Pose, Direction> = { face: 'center', gauche: 'left', droite: 'right' }
const INSTRUCTIONS: Record<Pose, string> = {
  face: 'Regardez droit vers la caméra',
  gauche: 'Tournez lentement la tête vers votre gauche',
  droite: 'Tournez lentement la tête vers votre droite',
}

/** Dessine les points du maillage en tenant compte du recadrage object-cover de la vidéo. */
function drawMesh(canvas: HTMLCanvasElement | null, video: HTMLVideoElement, points: Landmarks['points'], color: string) {
  if (!canvas) return
  const ctx = canvas.getContext('2d')
  if (!ctx) return
  const dpr = window.devicePixelRatio || 1
  const W = Math.round(canvas.clientWidth * dpr)
  const H = Math.round(canvas.clientHeight * dpr)
  if (!W || !H) return
  if (canvas.width !== W || canvas.height !== H) {
    canvas.width = W
    canvas.height = H
  }
  ctx.clearRect(0, 0, W, H)
  const vw = video.videoWidth
  const vh = video.videoHeight
  if (!points.length || !vw || !vh) return
  const s = Math.max(W / vw, H / vh)
  const ox = (W - vw * s) / 2
  const oy = (H - vh * s) / 2
  const r = 0.6 * dpr // points de 1.2 px
  ctx.globalAlpha = 0.7
  ctx.fillStyle = color
  ctx.beginPath()
  for (const p of points) {
    const x = ox + p.x * vw * s
    const y = oy + p.y * vh * s
    ctx.moveTo(x + r, y)
    ctx.arc(x, y, r, 0, Math.PI * 2)
  }
  ctx.fill()
}

function sameReading(a: LiveReading | null, b: LiveReading): boolean {
  if (!a || a.faces !== b.faces) return false
  if (a.rotation === null || b.rotation === null) return a.rotation === b.rotation
  return Math.round(a.rotation * 100) === Math.round(b.rotation * 100)
}

export function FaceScanner({
  mode,
  poses,
  camera,
  videoRef,
  detectorFactory = loadMediaPipeDetector,
  holdMs = 1000,
  verdict = 'idle',
  onComplete,
  onCancel,
  onCameraError,
  statusText,
  children,
}: FaceScannerProps) {
  const [engine, setEngine] = useState<Engine>('loading')
  const [cameraError, setCameraError] = useState(false)
  const [index, setIndex] = useState(0)
  const [done, setDone] = useState(false)
  const [live, setLive] = useState<LiveReading | null>(null)
  const [flash, setFlash] = useState(0)
  const [countdown, setCountdown] = useState<number | null>(null)
  const { progress, tick, reset } = useHoldTimer(holdMs)

  const canvasRef = useRef<HTMLCanvasElement>(null)
  const detectorRef = useRef<PoseDetector | null>(null)
  const factoryRef = useRef(detectorFactory)
  const posesRef = useRef(poses)
  const indexRef = useRef(0)
  const framesRef = useRef<FaceFrame[]>([])
  const pauseUntilRef = useRef(0)
  const lastRef = useRef<Landmarks | null>(null)
  const onCompleteRef = useRef(onComplete)
  const onCameraErrorRef = useRef(onCameraError)
  const verdictRef = useRef(verdict)
  useEffect(() => {
    posesRef.current = poses
    onCompleteRef.current = onComplete
    onCameraErrorRef.current = onCameraError
    verdictRef.current = verdict
  })

  const displayVerdict: Verdict = verdict !== 'idle' ? verdict : done ? 'analyzing' : 'idle'

  // Caméra : allumée au montage, toujours coupée au démontage.
  useEffect(() => {
    let alive = true
    camera.start().catch(() => {
      if (!alive) return
      setCameraError(true)
      onCameraErrorRef.current?.()
    })
    return () => {
      alive = false
      camera.stop()
    }
  }, [camera])

  // Détecteur : chargé une fois ; rejet ou délai dépassé => mode manuel.
  useEffect(() => {
    let settled = false
    let cancelled = false
    const timer = setTimeout(() => {
      if (settled) return
      settled = true
      setEngine('manual')
    }, DETECTOR_TIMEOUT_MS)
    factoryRef.current().then(
      (det) => {
        if (cancelled || settled) {
          det.close()
          return
        }
        settled = true
        clearTimeout(timer)
        detectorRef.current = det
        setEngine('auto')
      },
      () => {
        if (cancelled || settled) return
        settled = true
        clearTimeout(timer)
        setEngine('manual')
      },
    )
    return () => {
      cancelled = true
      clearTimeout(timer)
      detectorRef.current?.close()
      detectorRef.current = null
    }
  }, [])

  /** Capture la pose courante ; false si la caméra n'a pas pu fournir d'image. */
  const commit = useCallback(
    (ts: number): boolean => {
      const pose = posesRef.current[indexRef.current]
      if (!pose) return false
      let image: string
      try {
        image = camera.capture()
      } catch {
        reset()
        return false
      }
      framesRef.current = [...framesRef.current, { pose, image_b64: image }]
      reset()
      setFlash((f) => f + 1)
      const next = indexRef.current + 1
      indexRef.current = next
      pauseUntilRef.current = ts + STEP_PAUSE_MS
      setIndex(next)
      if (next >= posesRef.current.length) {
        setDone(true)
        // Les JPEG ne restent pas en mémoire pendant l'analyse / le verdict.
        const frames = framesRef.current
        framesRef.current = []
        onCompleteRef.current(frames)
      }
      return true
    },
    [camera, reset],
  )

  // Boucle de détection (mode auto). Continue après la dernière capture pour que le maillage
  // suive le visage pendant l'analyse, sans plus rien capturer.
  useEffect(() => {
    if (engine !== 'auto' || cameraError) return
    let raf = 0
    const loop = (ts: number) => {
      raf = requestAnimationFrame(loop)
      const det = detectorRef.current
      const video = videoRef.current
      if (!det || !video) return
      let lm: Landmarks | null
      try {
        lm = det.detect(video, ts)
      } catch {
        // Détecteur en panne en cours de route : on bascule en manuel plutôt que de bloquer.
        cancelAnimationFrame(raf)
        drawMesh(canvasRef.current, video, [], ACCENT) // efface le dernier maillage
        det.close()
        detectorRef.current = null
        setEngine('manual')
        return
      }
      if (lm) {
        lastRef.current = lm
        drawMesh(canvasRef.current, video, lm.points, MESH_COLORS[verdictRef.current])
        const reading = { rotation: lm.rotation, faces: lm.faces }
        setLive((prev) => (sameReading(prev, reading) ? prev : reading))
      }
      const expected = posesRef.current[indexRef.current]
      if (!expected) return
      const cur = lastRef.current
      // Pas de capture pendant la pause inter-pose ni sous un verdict affiché par le parent.
      const ok =
        verdictRef.current === 'idle' &&
        ts >= pauseUntilRef.current &&
        !!cur &&
        cur.faces === 1 &&
        meetsCapture(expected, cur.rotation)
      if (tick(ok, ts)) commit(ts)
    }
    raf = requestAnimationFrame(loop)
    return () => cancelAnimationFrame(raf)
  }, [engine, cameraError, tick, commit, videoRef])

  // Mode manuel : 3-2-1 puis capture.
  useEffect(() => {
    if (countdown === null) return
    const t = setTimeout(() => {
      if (countdown > 1) {
        setCountdown(countdown - 1)
      } else {
        setCountdown(null)
        // Comme en auto : rien n'est capturé sous un verdict affiché par le parent.
        if (verdictRef.current === 'idle') commit(performance.now())
      }
    }, 1000)
    return () => clearTimeout(t)
  }, [countdown, commit])

  const expected = done ? undefined : poses[index]
  const poseOk =
    engine === 'auto' && verdict === 'idle' && !!live && live.faces === 1 && !!expected && meetsCapture(expected, live.rotation)
  const manual = engine === 'manual'

  let instruction: string
  if (cameraError) instruction = 'Vérifiez la caméra du PC Hôte puis recommencez.'
  // Sous un verdict, c'est le calque de verdict (role=status) qui parle.
  else if (displayVerdict !== 'idle') instruction = ''
  else if (done || !expected) instruction = 'Captures terminées.'
  else if (engine === 'loading') instruction = 'Initialisation du capteur biométrique…'
  else if (manual) instruction = INSTRUCTIONS[expected]
  else if (!live || live.faces === 0) instruction = 'Placez votre visage dans le cadre'
  else if (live.faces > 1) instruction = 'Un seul visage doit être visible'
  else if (poseOk) instruction = 'Ne bougez plus…'
  // Bon sens mais pas assez franc pour la marge de capture : on encourage à continuer.
  else if (expected === 'gauche' && (live.rotation ?? 0) > 0) instruction = 'Tournez encore un peu vers votre gauche'
  else if (expected === 'droite' && (live.rotation ?? 0) < 0) instruction = 'Tournez encore un peu vers votre droite'
  else instruction = INSTRUCTIONS[expected]

  const shownProgress = manual ? (countdown === null ? 0 : (COUNTDOWN_FROM - countdown) / COUNTDOWN_FROM) : progress
  const step = `POSE ${Math.min(index + 1, poses.length)}/${poses.length}`
  const telemetry = manual
    ? `MODE MANUEL · ${step}`
    : `ROT ${formatRotation(live?.rotation ?? null)} · FACES ${live?.faces ?? 0} · POSE ${poseOk ? 'OK' : '--'}`

  return (
    <section
      className="fs-root relative isolate aspect-[3/4] min-h-[380px] w-full overflow-hidden rounded-[22px] bg-night select-none sm:aspect-[4/3] sm:min-h-[400px]"
      aria-label="Scan biométrique du visage"
      data-verdict={displayVerdict}
      data-engine={engine}
    >
      {/* Couche miroir : seule la vidéo et le maillage sont retournés (cf. ORIENTATION). */}
      <div className="fs-mirror absolute inset-0 scale-x-[-1]">
        <video
          ref={videoRef}
          data-testid="camera"
          autoPlay
          muted
          playsInline
          className="fs-video h-full w-full object-cover"
        />
        <canvas ref={canvasRef} className="pointer-events-none absolute inset-0 h-full w-full" aria-hidden />
      </div>
      <div className="fs-vignette pointer-events-none absolute inset-0" aria-hidden />
      <div className="fs-tint pointer-events-none absolute inset-0" aria-hidden />

      <HudOverlay
        mode={mode}
        poses={poses}
        index={index}
        engine={engine}
        live={live}
        expected={expected}
        poseOk={poseOk}
        progress={shownProgress}
        direction={expected ? DIRECTIONS[expected] : null}
        countdown={countdown}
        verdict={displayVerdict}
        statusText={statusText}
      />

      {flash > 0 && <div key={flash} className="fs-flash" aria-hidden />}
      <VerdictOverlay verdict={displayVerdict} mode={mode} />

      {cameraError && (
        <div className="fs-error" role="alert">
          <span className="fs-error-code">ERR · CAM</span>
          Caméra inaccessible sur le PC Hôte.
        </div>
      )}

      {/* Pied de cadre : consigne (annoncée), action manuelle, contenu parent, télémétrie. */}
      <div className="fs-footer absolute inset-x-0 bottom-0 z-30 flex flex-col items-center gap-2.5 px-3.5 pb-3 pt-12 sm:px-4 sm:pb-3.5">
        {engine === 'auto' && !done && displayVerdict === 'idle' && (
          <YawGauge rotation={live?.rotation ?? null} expected={expected} />
        )}
        <p
          data-testid="fs-instruction"
          aria-live="polite"
          aria-atomic="true"
          className="fs-instruction min-h-[1.4em] text-center text-[15px] font-medium tracking-[-0.01em] text-[#f3f4f6]"
        >
          {instruction}
        </p>
        {manual && !done && !cameraError && displayVerdict === 'idle' && (
          <button
            type="button"
            className="fs-btn"
            onClick={() => setCountdown(COUNTDOWN_FROM)}
            disabled={countdown !== null}
          >
            Capturer
          </button>
        )}
        {children && <div className="w-full">{children}</div>}
        <div className="fs-label flex w-full items-center justify-between gap-3">
          <span className="fs-telemetry tnum" aria-hidden data-ok={poseOk}>
            {telemetry}
          </span>
          {onCancel && (
            <button type="button" className="fs-link" onClick={onCancel}>
              Annuler
            </button>
          )}
        </div>
      </div>
    </section>
  )
}
