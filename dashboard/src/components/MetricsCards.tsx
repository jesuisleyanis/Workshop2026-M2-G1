import type { ReactNode } from 'react'
import { formatDuration } from '../lib/format'
import { currentThreshold, incidentMttr, scoreLevel } from '../lib/state'
import type { Incident, ScoreSample, VerifyTx } from '../types/events'
import { Pill } from './Panel'

function Kpi({ title, aside, children }: { title: string; aside: ReactNode; children: ReactNode }) {
  return (
    <div className="card gap-3.5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="min-w-0 truncate text-[13px] text-mute" title={title}>{title}</span>
        {aside}
      </div>
      {children}
    </div>
  )
}

const BIG = 'tnum text-[42px] font-medium leading-none tracking-[-0.03em]'

/** Score courant du service suivi + 12 dernières barres. */
export function ScoreCard({ score, history }: { score: ScoreSample | null; history: ScoreSample[] }) {
  const threshold = currentThreshold({ score })
  const level = score ? scoreLevel(score.score, threshold) : 'none'
  const above = level === 'alert'
  const bars = score ? history.filter((h) => h.service === score.service).slice(-12) : []
  return (
    <Kpi
      title={`Score d'anomalie · ${score?.service ?? '—'}`}
      aside={
        <Pill tone={above ? 'ko' : 'ok'}>
          {!score ? `seuil ${threshold.toFixed(2)}` : above ? 'au-dessus du seuil' : `sous le seuil ${threshold.toFixed(2)}`}
        </Pill>
      }
    >
      <div className="flex items-end justify-between gap-3" data-testid="score-gauge" data-level={level}>
        <span className={`${BIG} ${above ? 'text-ko' : ''}`} data-testid="score-value">
          {score ? score.score.toFixed(2) : '—'}
        </span>
        <div className="flex h-[34px] items-end gap-[3px]" aria-hidden>
          {bars.map((b, i) => (
            <div key={i} className={`w-1 rounded-[2px] ${b.score >= threshold ? 'bg-ko' : 'bg-accent'}`} style={{ height: Math.max(3, Math.min(1, b.score) * 34) }} />
          ))}
        </div>
      </div>
    </Kpi>
  )
}

interface MetricsProps {
  incident: Incident | null
  /** Horloge (ms epoch) pour le compteur live. */
  now: number
}

export function MetricsCards({ incident, now }: MetricsProps) {
  const open = incident !== null && incident.verification === null && incident.failure === null
  const mttr = incident ? incidentMttr(incident) : null
  const live = open && incident ? Math.max(0, (now - Date.parse(incident.detectedAt)) / 1000) : null
  const verified = incident?.verification?.ok === true
  const mttd = incident?.mttdSeconds ?? null

  return (
    <>
      <Kpi title="MTTD · détection" aside={<span className="text-xs text-mute-3">secondes</span>}>
        <div className="flex flex-col gap-1.5">
          <span className={`${BIG} ${mttd === null ? 'text-mute-4' : ''}`} data-testid="metric-mttd">{formatDuration(mttd)}</span>
          <span className="text-xs text-mute-2">{verified ? 'mesuré par le moteur' : incident ? 'mesure à la vérification' : 'aucun incident'}</span>
        </div>
      </Kpi>
      <Kpi title="MTTR · rétablissement" aside={<span className="text-xs text-mute-3">secondes</span>}>
        <div className="flex flex-col gap-1.5">
          <span className={`${BIG} ${live !== null ? 'text-warn' : mttr === null ? 'text-mute-4' : ''}`} data-testid="metric-mttr">
            {formatDuration(live ?? mttr)}
          </span>
          <span className="text-xs text-mute-2">
            {live !== null ? 'chronomètre en cours' : verified ? 'détection → service vérifié' : incident?.failure ? 'non rétabli' : 'aucun incident'}
          </span>
        </div>
      </Kpi>
    </>
  )
}

export function VerificationCard({ verify, now }: { verify: VerifyTx | null; now: number }) {
  const ago = verify ? Math.max(0, Math.round((now - Date.parse(verify.ts)) / 1000)) : 0
  return (
    <Kpi
      title="Transaction de vérification"
      aside={<Pill tone={!verify ? 'mute' : verify.ok ? 'ok' : 'ko'}>{!verify ? 'aucune' : verify.ok ? 'OK' : 'ÉCHEC'}</Pill>}
    >
      <div className="flex flex-col gap-1.5" data-testid="verification" data-ok={verify ? verify.ok : undefined}>
        <span className={`${BIG} ${verify ? '' : 'text-mute-4'}`}>
          {verify?.durationMs != null ? Math.round(verify.durationMs) : '—'}
          <span className="ml-1 text-base text-mute-2">ms</span>
        </span>
        <span className="truncate font-mono text-xs text-mute-2">
          {verify ? (
            <>
              <span>{verify.txId ?? '—'}</span> · il y a {ago} s
            </>
          ) : (
            'Aucune vérification reçue.'
          )}
        </span>
      </div>
    </Kpi>
  )
}
