import type { ServiceHealth, ServiceStatus } from '../types/events'
import { Panel, Pill, TONE, type Tone } from './Panel'

const UI: Record<ServiceStatus, { text: string; tone: Tone }> = {
  up: { text: 'Opérationnel', tone: 'ok' },
  degraded: { text: 'Dégradé', tone: 'warn' },
  down: { text: 'Hors service', tone: 'ko' },
  unknown: { text: 'Inconnu', tone: 'mute' },
}

export function ServicesGrid({ services }: { services: ServiceHealth[] }) {
  const known = services.some((s) => s.status !== 'unknown')
  const up = services.filter((s) => s.status === 'up').length
  return (
    <Panel title="État des services" aside={<span className="text-xs text-mute-2">{known ? `${up}/${services.length} opérationnels` : 'en attente de health'}</span>}>
      <ul className="flex flex-col">
        {services.map((s) => {
          const ui = UI[s.status]
          const t = TONE[ui.tone]
          return (
            <li key={s.name} data-service={s.name} data-status={s.status} title={s.detail} className="flex items-center justify-between border-b border-[#1f1f23] py-[9px] last:border-b-0">
              <span className="flex items-center gap-2.5">
                <span className={`h-2 w-2 rounded-full ${t.solid}`} style={{ boxShadow: '0 0 0 3px rgb(255 255 255 / 0.04)' }} aria-hidden />
                <span className="font-mono text-[13px]">{s.name}</span>
              </span>
              <Pill tone={ui.tone}>{ui.text}</Pill>
            </li>
          )
        })}
      </ul>
    </Panel>
  )
}
