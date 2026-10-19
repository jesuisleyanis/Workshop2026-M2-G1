import type { ServiceHealth, ServiceStatus } from '../types/events'
import { Panel } from './Panel'

const UI: Record<ServiceStatus, { text: string; dot: string; label: string }> = {
  up: { text: 'OPÉRATIONNEL', dot: 'bg-emerald-400', label: 'text-emerald-300' },
  degraded: { text: 'DÉGRADÉ', dot: 'bg-amber-400', label: 'text-amber-300' },
  down: { text: 'HORS SERVICE', dot: 'bg-red-500', label: 'text-red-300' },
  unknown: { text: 'INCONNU', dot: 'bg-slate-600', label: 'text-slate-500' },
}

export function ServicesGrid({ services }: { services: ServiceHealth[] }) {
  return (
    <Panel title="État des services">
      <ul className="grid grid-cols-2 gap-3">
        {services.map((s) => {
          const ui = UI[s.status]
          return (
            <li key={s.name} data-service={s.name} data-status={s.status} className="rounded-xl bg-slate-950/60 px-4 py-3" title={s.detail}>
              <p className="flex items-center gap-2 text-lg font-bold text-slate-100">
                <span className={`h-3.5 w-3.5 rounded-full ${ui.dot}`} aria-hidden />
                {s.name}
              </p>
              <p className={`text-sm font-bold tracking-widest ${ui.label}`}>{ui.text}</p>
            </li>
          )
        })}
      </ul>
    </Panel>
  )
}
