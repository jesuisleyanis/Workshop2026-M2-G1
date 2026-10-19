import { GRAFANA_BASE } from '../config'

export function grafanaLinks(base: string): { label: string; href: string }[] {
  return [
    { label: 'Dashboards', href: `${base}/dashboards` },
    { label: 'Explore · Loki', href: `${base}/explore` },
    { label: 'Alertes SOC', href: `${base}/alerting/list` },
  ]
}

/** Lien Explore pré-rempli (datasources provisionnées : uid `prometheus` et `loki`). */
export function exploreLink(base: string, datasource: 'prometheus' | 'loki', expr: string): string {
  const left = { datasource, queries: [{ refId: 'A', expr }], range: { from: 'now-15m', to: 'now' } }
  return `${base}/explore?left=${encodeURIComponent(JSON.stringify(left))}`
}

export function GrafanaLinks({ base = GRAFANA_BASE }: { base?: string }) {
  return (
    <nav aria-label="Liens Grafana" className="flex flex-col gap-1">
      <span className="px-2 pb-1.5 text-xs text-mute-2">Grafana</span>
      {grafanaLinks(base).map((l) => (
        <a
          key={l.href}
          href={l.href}
          target="_blank"
          rel="noopener noreferrer"
          className="flex h-[34px] items-center justify-between rounded-[9px] px-2.5 text-[13px] text-fg-2 hover:bg-card-2 hover:text-white"
        >
          <span>{l.label}</span>
          <span className="text-xs text-mute-3" aria-hidden>↗</span>
        </a>
      ))}
      <span className="break-all px-2.5 pt-1 font-mono text-[10px] text-mute-4">{base}</span>
    </nav>
  )
}
