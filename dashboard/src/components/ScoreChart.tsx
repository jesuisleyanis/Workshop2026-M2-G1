import type { Incident, ScoreSample } from '../types/events'
import { Panel } from './Panel'

export const WINDOW_MS = 120_000
const W = 600
const H = 200

/** Points SVG (x en px sur W, y inversé sur H) des échantillons dans la fenêtre glissante. */
export function chartPoints(samples: ScoreSample[], now: number, windowMs = WINDOW_MS): [number, number][] {
  const x0 = now - windowMs
  return samples
    .map((s) => ({ t: Date.parse(s.ts), v: Math.min(1, Math.max(0, s.score)) }))
    .filter((p) => p.t >= x0 - 2000)
    .map((p) => [Math.max(0, ((p.t - x0) / windowMs) * W), (1 - p.v) * H])
}

interface Props {
  history: ScoreSample[]
  services: string[]
  focus: string | null
  onFocus: (service: string) => void
  threshold: number
  incident: Incident | null
  now: number
}

export function ScoreChart({ history, services, focus, onFocus, threshold, incident, now }: Props) {
  const samples = focus ? history.filter((h) => h.service === focus) : []
  const pts = chartPoints(samples, now)
  const line = pts.length > 1 ? `M${pts.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(' L')}` : ''
  const area = line && `${line} L${pts.at(-1)![0].toFixed(1)},${H} L${pts[0]![0].toFixed(1)},${H} Z`
  const thr = Math.min(1, Math.max(0, threshold))
  const x0 = now - WINDOW_MS
  // Étiquettes : détection en haut, vérification en bas (évite le chevauchement d'un MTTR court),
  // ancrées à gauche du trait près du bord droit.
  const markers: { pct: number; label: string; cls: string; pos: string }[] = []
  if (incident && incident.service === focus) {
    const det = Date.parse(incident.detectedAt)
    if (det >= x0) markers.push({ pct: ((det - x0) / WINDOW_MS) * 100, label: 'Détection', cls: 'border-warn text-warn', pos: 'top-1' })
    const ver = incident.verification?.ok ? Date.parse(incident.verification.ts) : NaN
    if (ver >= x0) markers.push({ pct: ((ver - x0) / WINDOW_MS) * 100, label: 'Vérifié', cls: 'border-ok text-ok', pos: 'bottom-1' })
  }

  return (
    <Panel
      title="Historique du score"
      subtitle={`Fenêtre glissante 2 min · seuil ${thr.toFixed(2)}`}
      aside={
        services.length > 0 && (
          <div role="tablist" aria-label="Service affiché" className="flex gap-1 rounded-[10px] border border-edge-2 bg-[#0f0f11] p-[3px]">
            {services.map((s) => (
              <button
                key={s}
                type="button"
                role="tab"
                aria-selected={s === focus}
                onClick={() => onFocus(s)}
                className={`h-7 cursor-pointer rounded-[7px] px-3 text-xs ${s === focus ? 'bg-edge text-fg' : 'text-mute-2 hover:text-fg-2'}`}
              >
                {s}
              </button>
            ))}
          </div>
        )
      }
    >
      <div className="relative ml-7 h-[220px]">
        {(['1.0', '0.5', '0.0'] as const).map((l, i) => (
          <span key={l} className="absolute -left-7 font-mono text-[10px] text-mute-4" style={{ top: `calc(${i * 50}% - 6px)` }}>
            {l}
          </span>
        ))}
        <div className="absolute inset-0 border-t border-b border-dashed border-t-[#1f1f23] border-b-edge" />
        <div className="absolute inset-x-0 top-1/2 border-t border-dashed border-[#1f1f23]" />
        <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" className="absolute inset-0 h-full w-full overflow-visible" role="img" aria-label={`Score d'anomalie de ${focus ?? 'aucun service'} sur 2 minutes`}>
          <defs>
            <linearGradient id="ztrLine" x1="0" y1="0" x2="0" y2={H} gradientUnits="userSpaceOnUse">
              <stop offset="0" stopColor="#f87171" />
              <stop offset={1 - thr} stopColor="#f87171" />
              <stop offset={1 - thr} stopColor="#a78bfa" />
              <stop offset="1" stopColor="#a78bfa" />
            </linearGradient>
            <linearGradient id="ztrArea" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0" stopColor="#a78bfa" stopOpacity="0.22" />
              <stop offset="1" stopColor="#a78bfa" stopOpacity="0" />
            </linearGradient>
          </defs>
          {area && <path d={area} fill="url(#ztrArea)" />}
          {line && <path d={line} fill="none" stroke="url(#ztrLine)" strokeWidth="2" vectorEffect="non-scaling-stroke" strokeLinejoin="round" />}
        </svg>
        <div className="absolute inset-x-0 border-t border-dashed border-ko opacity-70" style={{ top: `${(1 - thr) * 100}%` }} />
        <span className="absolute right-0 -translate-y-[120%] font-mono text-[10px] text-ko" style={{ top: `${(1 - thr) * 100}%` }}>
          seuil {thr.toFixed(2)}
        </span>
        {markers.map((m) => (
          <div key={m.label} className={`absolute inset-y-0 border-l ${m.cls}`} style={{ left: `${Math.min(100, m.pct).toFixed(2)}%` }}>
            <span className={`absolute ${m.pos} ${m.pct > 80 ? 'right-1.5' : 'left-1.5'} whitespace-nowrap rounded bg-card px-1 text-[11px]`}>{m.label}</span>
          </div>
        ))}
        {pts.length < 2 && <div className="absolute inset-0 grid place-items-center text-[13px] text-mute-3">En attente d'événements score…</div>}
      </div>
      <div className="ml-7 flex justify-between font-mono text-[10px] text-mute-4">
        <span>−120 s</span>
        <span>−60 s</span>
        <span>maintenant</span>
      </div>
    </Panel>
  )
}
