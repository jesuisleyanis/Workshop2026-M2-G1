import type { ReactNode } from 'react'
import type { Pose } from '../../api/auth'
import { CAPTURE_FACE_MAX, CAPTURE_PROFILE_MIN } from './captureMargins'

// Couches HUD du FaceScanner (purement visuelles, hors couche miroir : textes et flèches
// restent lisibles). Toute la mise en scène sci-fi vit ici et dans scanner.css (préfixe fs-).

export type Engine = 'loading' | 'auto' | 'manual'
export type Verdict = 'idle' | 'analyzing' | 'granted' | 'denied'
/** Sens de la consigne TEL QUE VU dans l'aperçu miroir. */
export type Direction = 'left' | 'right' | 'center'
export interface LiveReading {
  rotation: number | null
  faces: number
}

export const POSE_CODES: Record<Pose, string> = { face: 'FACE', gauche: 'PROFIL G', droite: 'PROFIL D' }
const GLYPHS: Record<Direction, string> = { left: '←', right: '→', center: '●' }
const TICKS = 60

// Jauge de lacet : ±0.4 de rotation sur toute la largeur, INVERSÉE pour suivre le miroir
// (rotation > 0 = tête vers la gauche de la personne = vers la gauche de l'écran).
const GAUGE_SPAN = 0.4
const gaugeX = (r: number) => 50 - (Math.max(-GAUGE_SPAN, Math.min(GAUGE_SPAN, r)) / GAUGE_SPAN) * 50
// Zones cibles = marges de capture (cf. captureMargins.ts), pas les seuils bruts du contrat.
const ZONES: Record<Pose, { left: number; width: number }> = {
  gauche: { left: 0, width: gaugeX(CAPTURE_PROFILE_MIN) },
  face: { left: gaugeX(CAPTURE_FACE_MAX), width: gaugeX(-CAPTURE_FACE_MAX) - gaugeX(CAPTURE_FACE_MAX) },
  droite: { left: gaugeX(-CAPTURE_PROFILE_MIN), width: 100 - gaugeX(-CAPTURE_PROFILE_MIN) },
}

export function formatRotation(r: number | null): string {
  if (r === null) return ' --- '
  return `${r >= 0 ? '+' : '-'}${Math.abs(r).toFixed(2)}`
}

export interface HudOverlayProps {
  mode: 'verify' | 'enroll'
  poses: Pose[]
  index: number
  engine: Engine
  live: LiveReading | null
  expected: Pose | undefined
  poseOk: boolean
  progress: number
  direction: Direction | null
  countdown: number | null
  verdict: Verdict
  statusText?: string
}

export function HudOverlay(p: HudOverlayProps) {
  const lit = Math.round(p.progress * TICKS)
  const scanning = p.verdict === 'idle'
  return (
    <>
      <div className="fs-grid pointer-events-none absolute inset-0" aria-hidden />
      {p.verdict !== 'granted' && p.verdict !== 'denied' && <div className="fs-scan" aria-hidden />}

      {/* Barre haute : titre + mode, statut parent, état du capteur. */}
      <div className="absolute inset-x-0 top-0 z-10 flex flex-col gap-2 px-3.5 pt-3 sm:px-4 sm:pt-3.5">
        <div className="fs-label flex items-center justify-between gap-3">
          <span className="flex min-w-0 items-center gap-2">
            <span className="fs-dot" aria-hidden />
            <span className="truncate">
              SCAN BIOMÉTRIQUE <span className="fs-dim fs-wide">/ {p.mode === 'verify' ? 'VÉRIFICATION' : 'ENRÔLEMENT'}</span>
            </span>
          </span>
          <span className="flex shrink-0 items-center gap-2.5">
            {p.statusText && <span className="fs-tag">{p.statusText}</span>}
            <span className="fs-dim fs-wide">
              {p.engine === 'manual' ? 'MODE MANUEL' : p.engine === 'loading' ? 'INIT' : 'AUTO'}
            </span>
            <span className="flex items-center gap-1.5">
              <span className="fs-rec" aria-hidden />
              LIVE
            </span>
          </span>
        </div>
        <ol className="flex flex-wrap gap-1.5" aria-label="Poses à capturer">
          {p.poses.map((pose, i) => {
            const state = i < p.index ? 'done' : i === p.index && scanning ? 'active' : 'pending'
            return (
              <li key={`${pose}-${i}`} className="fs-chip" data-state={state} aria-current={state === 'active' ? 'step' : undefined}>
                <span className="fs-chip-num">{state === 'done' ? '✓' : String(i + 1).padStart(2, '0')}</span>
                {POSE_CODES[pose]}
                {state === 'done' && <span className="sr-only"> (validée)</span>}
              </li>
            )
          })}
        </ol>
      </div>

      {/* Scène centrale : réticule, anneau de maintien, flèche de consigne, compte à rebours. */}
      <div className="fs-stage" data-lock={p.poseOk && scanning} data-engine={p.engine} aria-hidden>
        <div className="fs-reticle">
          <span className="fs-corner fs-tl" />
          <span className="fs-corner fs-tr" />
          <span className="fs-corner fs-bl" />
          <span className="fs-corner fs-br" />
        </div>
        <svg viewBox="0 0 100 100" className="fs-ring">
          <g>
            {Array.from({ length: TICKS }, (_, i) => (
              <line
                key={i}
                x1="50"
                y1="0.8"
                x2="50"
                y2={i % 5 === 0 ? 3.8 : 2.6}
                transform={`rotate(${i * (360 / TICKS)} 50 50)`}
                className={i < lit ? 'fs-tick fs-tick-on' : 'fs-tick'}
              />
            ))}
          </g>
          <circle cx="50" cy="50" r="45.5" className="fs-ring-track" />
          <circle
            cx="50"
            cy="50"
            r="45.5"
            pathLength={100}
            strokeDasharray="100"
            strokeDashoffset={100 - 100 * p.progress}
            transform="rotate(-90 50 50)"
            className="fs-ring-progress"
          />
          <circle cx="50" cy="50" r="41" className="fs-orbit" />
        </svg>
        {p.direction && scanning && (
          <span
            className="fs-arrow"
            data-testid="fs-arrow"
            data-direction={p.direction}
            data-hold={p.poseOk && p.engine === 'auto'}
          >
            {p.direction === 'center' ? (
              <span className="fs-arrow-glyph">{GLYPHS.center}</span>
            ) : (
              [0, 1, 2].map((i) => (
                <span key={i} className="fs-arrow-glyph" style={{ animationDelay: `${i * 140}ms` }}>
                  {GLYPHS[p.direction as Direction]}
                </span>
              ))
            )}
          </span>
        )}
        {p.countdown !== null && (
          <span key={p.countdown} className="fs-countdown" data-testid="fs-countdown">
            {p.countdown}
          </span>
        )}
      </div>
    </>
  )
}

/** Jauge de lacet (vue miroir) avec la zone cible de la pose attendue. */
export function YawGauge({ rotation, expected }: { rotation: number | null; expected: Pose | undefined }) {
  const zone = expected ? ZONES[expected] : null
  return (
    <div className="fs-gauge" aria-hidden>
      <span className="fs-gauge-end">G</span>
      <div className="fs-gauge-track">
        {zone && <span className="fs-gauge-zone" style={{ left: `${zone.left}%`, width: `${zone.width}%` }} />}
        <span className="fs-gauge-mid" />
        {rotation !== null && <span className="fs-gauge-marker" style={{ left: `${gaugeX(rotation)}%` }} />}
      </div>
      <span className="fs-gauge-end">D</span>
    </div>
  )
}

const VERDICT_TEXT: Record<'verify' | 'enroll', Record<Exclude<Verdict, 'idle'>, [string, string]>> = {
  verify: {
    analyzing: ['ANALYSE BIOMÉTRIQUE', 'Comparaison avec l’empreinte enrôlée'],
    granted: ['IDENTITÉ CONFIRMÉE', 'Correspondance validée'],
    denied: ['NON RECONNU', 'Aucune correspondance'],
  },
  enroll: {
    analyzing: ['ANALYSE BIOMÉTRIQUE', 'Calcul de l’empreinte faciale'],
    granted: ['EMPREINTE ENREGISTRÉE', 'Enrôlement validé'],
    denied: ['CAPTURE REJETÉE', 'Recommencez le scan'],
  },
}

/** Calque de verdict, piloté par le parent (role=status : annoncé aux lecteurs d'écran). */
export function VerdictOverlay({ verdict, mode }: { verdict: Verdict; mode: 'verify' | 'enroll' }) {
  if (verdict === 'idle') return null
  const [title, sub] = VERDICT_TEXT[mode][verdict]
  let emblem: ReactNode
  if (verdict === 'analyzing') {
    emblem = (
      <svg viewBox="0 0 100 100" className="fs-emblem" aria-hidden>
        <circle cx="50" cy="50" r="44" className="fs-an-ring fs-spin-cw" />
        <circle cx="50" cy="50" r="34" className="fs-an-ring fs-an-ring-2 fs-spin-ccw" />
        <circle cx="50" cy="50" r="24" className="fs-an-ring fs-an-ring-3 fs-spin-cw-fast" />
        <circle cx="50" cy="50" r="7" className="fs-an-core" />
      </svg>
    )
  } else {
    emblem = (
      <svg viewBox="0 0 100 100" className="fs-emblem" aria-hidden>
        <circle cx="50" cy="50" r="40" className="fs-em-ring" />
        {verdict === 'granted' ? (
          <path d="M32 51 L45 64 L69 38" pathLength={1} className="fs-em-mark" />
        ) : (
          <path d="M36 36 L64 64 M64 36 L36 64" pathLength={1} className="fs-em-mark" />
        )}
      </svg>
    )
  }
  return (
    <div className="fs-verdict" data-kind={verdict} role="status" aria-label="Verdict">
      {emblem}
      <p className="fs-verdict-title" data-text={title}>
        {title}
      </p>
      <p className="fs-verdict-sub">{sub}</p>
    </div>
  )
}
