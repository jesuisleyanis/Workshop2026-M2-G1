import { currentThreshold, scoreLevel, type ScoreLevel } from '../lib/state'
import type { ScoreSample } from '../types/events'
import { Panel } from './Panel'

const CX = 100
const CY = 100
const R = 80

/** Point sur le demi-cercle pour une valeur v dans [0,1] (0 = gauche, 1 = droite). */
export function gaugePoint(v: number, radius = R): { x: number; y: number } {
  const phi = Math.PI * (1 - Math.min(1, Math.max(0, v)))
  return { x: CX + radius * Math.cos(phi), y: CY - radius * Math.sin(phi) }
}

const COLORS: Record<ScoreLevel, { stroke: string; text: string; label: string }> = {
  normal: { stroke: '#34d399', text: 'text-emerald-300', label: 'NORMAL' },
  warning: { stroke: '#fbbf24', text: 'text-amber-300', label: 'VIGILANCE' },
  alert: { stroke: '#f87171', text: 'text-red-300', label: 'ANOMALIE' },
}

export function Sparkline({ history, threshold }: { history: ScoreSample[]; threshold: number }) {
  const W = 300
  const H = 60
  if (history.length < 2) return <div className="h-[60px]" aria-hidden />
  const pts = history.map((s, i) => `${((i / (history.length - 1)) * W).toFixed(1)},${(H - Math.min(1, s.score) * H).toFixed(1)}`)
  const ty = H - Math.min(1, threshold) * H
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="h-[60px] w-full" role="img" aria-label="Historique du score d'anomalie" preserveAspectRatio="none">
      <line x1="0" x2={W} y1={ty} y2={ty} stroke="#f87171" strokeDasharray="4 4" strokeWidth="1" />
      <polyline points={pts.join(' ')} fill="none" stroke="#94a3b8" strokeWidth="2" vectorEffect="non-scaling-stroke" />
    </svg>
  )
}

interface Props {
  score: ScoreSample | null
  history: ScoreSample[]
}

export function ScoreGauge({ score, history }: Props) {
  const threshold = currentThreshold({ score })
  const value = score?.score ?? 0
  const level = scoreLevel(value, threshold)
  const c = COLORS[level]
  const start = gaugePoint(0)
  const end = gaugePoint(1)
  const arc = `M ${start.x} ${start.y} A ${R} ${R} 0 0 1 ${end.x} ${end.y}`
  const t1 = gaugePoint(threshold, R - 12)
  const t2 = gaugePoint(threshold, R + 12)

  return (
    <Panel title="Score d'anomalie (ML)" aside={<span className="text-sm text-slate-500">{score?.service ?? '--'}</span>}>
      <div data-testid="score-gauge" data-level={score ? level : 'none'}>
        <svg viewBox="0 0 200 118" className="mx-auto w-full max-w-sm" role="img" aria-label={`Score ${value.toFixed(2)} pour un seuil de ${threshold.toFixed(2)}`}>
          <path d={arc} fill="none" stroke="#1e293b" strokeWidth="16" strokeLinecap="round" pathLength={100} />
          <path
            d={arc}
            fill="none"
            stroke={c.stroke}
            strokeWidth="16"
            strokeLinecap="round"
            pathLength={100}
            strokeDasharray={`${Math.min(1, value) * 100} 100`}
            style={{ transition: 'stroke-dasharray 400ms ease, stroke 400ms ease' }}
          />
          <line x1={t1.x} y1={t1.y} x2={t2.x} y2={t2.y} stroke="#f8fafc" strokeWidth="3" />
        </svg>
        <div className="-mt-14 text-center">
          <p className={`text-6xl font-black tabular-nums ${score ? c.text : 'text-slate-600'}`} data-testid="score-value">
            {score ? value.toFixed(2) : '--'}
          </p>
          <p className={`mt-1 text-lg font-bold tracking-widest ${score ? c.text : 'text-slate-600'}`}>{score ? c.label : 'EN ATTENTE'}</p>
          <p className="mt-1 text-sm text-slate-400">seuil de détection : {threshold.toFixed(2)}</p>
        </div>
        <div className="mt-4">
          <Sparkline history={history} threshold={threshold} />
        </div>
      </div>
    </Panel>
  )
}
