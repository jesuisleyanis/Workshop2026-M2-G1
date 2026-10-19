import { GRAFANA_BASE } from '../config'

export function grafanaLinks(base: string): { label: string; href: string }[] {
  return [
    { label: 'Dashboards Grafana', href: `${base}/dashboards` },
    { label: 'Logs (Explore / Loki)', href: `${base}/explore` },
    { label: 'Alertes', href: `${base}/alerting/list` },
  ]
}

export function GrafanaLinks({ base = GRAFANA_BASE }: { base?: string }) {
  return (
    <nav aria-label="Liens Grafana" className="flex flex-wrap items-center gap-3">
      <span className="text-sm uppercase tracking-[0.18em] text-slate-500">Observabilité</span>
      {grafanaLinks(base).map((l) => (
        <a
          key={l.href}
          href={l.href}
          target="_blank"
          rel="noopener noreferrer"
          className="rounded-lg border border-slate-700 px-4 py-2 text-base font-semibold text-sky-300 hover:border-sky-400 hover:bg-sky-500/10 focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-400"
        >
          {l.label} ↗
        </a>
      ))}
    </nav>
  )
}
