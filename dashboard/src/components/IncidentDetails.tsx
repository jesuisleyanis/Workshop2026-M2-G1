import { formatTime } from '../lib/format'
import { PLAYBOOKS, actionLabel } from '../lib/state'
import type { ActionResult, Incident } from '../types/events'
import { exploreLink } from './GrafanaLinks'
import { Panel, Pill, type Tone } from './Panel'

const RESULT: Record<ActionResult | 'running', { text: string; tone: Tone }> = {
  ok: { text: 'ok', tone: 'ok' },
  failed: { text: 'échec', tone: 'ko' },
  skipped: { text: 'ignorée', tone: 'mute' },
  running: { text: 'en cours', tone: 'warn' },
}

const params = (p?: Record<string, unknown>) =>
  Object.entries(p ?? {})
    .map(([k, v]) => `${k}=${String(v)}`)
    .join(' · ')

interface ActionRow {
  type: string
  result: ActionResult | 'running'
  ts: string | null
  meta: string
}

/** Actions annoncées par la décision, complétées par leur dernier résultat ; puis les actions hors plan. */
export function actionRows(i: Incident | null): ActionRow[] {
  if (!i) return []
  const planned = i.decision?.actions ?? []
  const rows: ActionRow[] = planned.map((p) => {
    const r = i.actions.findLast((a) => a.type === p.type)
    const expected = params(p.params)
    // Le moteur peut renvoyer les paramètres en `detail` : on ne les répète pas.
    const detail = r?.detail && r.detail.replace(/\s+/g, ' ') !== expected.replace(/ · /g, ' ') ? r.detail : null
    const meta = [expected, detail, r?.attempt ? `tentative ${r.attempt}` : null].filter(Boolean).join(' — ')
    return { type: p.type, result: r?.result ?? (i.failure ? 'skipped' : 'running'), ts: r?.ts ?? null, meta: meta || '—' }
  })
  for (const a of i.actions) {
    if (planned.some((p) => p.type === a.type)) continue
    rows.push({ type: a.type, result: a.result, ts: a.ts, meta: [a.detail, a.attempt ? `tentative ${a.attempt}` : null].filter(Boolean).join(' — ') || '—' })
  }
  return rows
}

export function ActionsPanel({ incident }: { incident: Incident | null }) {
  const rows = actionRows(incident)
  const ok = rows.filter((r) => r.result === 'ok').length
  return (
    <Panel title="Actions de remédiation" aside={<span className="text-xs text-mute-2">{rows.length ? `${ok}/${rows.length} réussie(s)` : '—'}</span>}>
      {rows.length ? (
        <ul className="flex flex-col gap-2">
          {rows.map((r) => (
            <li key={r.type} data-action={r.type} data-result={r.result} className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-edge bg-card-2 px-3.5 py-3">
              <div className="flex min-w-0 flex-col gap-1">
                <span className="font-mono text-sm">{r.type}</span>
                <span className="text-xs break-words text-mute-2">
                  {actionLabel(r.type)} · {r.meta}
                </span>
              </div>
              <div className="flex items-center gap-2.5">
                {r.ts && <span className="font-mono text-[11px] text-mute-3">{formatTime(r.ts)}</span>}
                <Pill tone={RESULT[r.result].tone}>{RESULT[r.result].text}</Pill>
              </div>
            </li>
          ))}
        </ul>
      ) : (
        <div className="rounded-xl border border-dashed border-[#2a2a2f] p-[18px] text-[13px] text-mute-3">
          Aucune action exécutée. Le moteur attend un événement remediation_started.
        </div>
      )}
    </Panel>
  )
}

export function SignalsPanel({ incident }: { incident: Incident | null }) {
  const feats = incident?.anomaly?.features_top ?? []
  const maxZ = Math.max(1, ...feats.map((f) => Math.abs(f.z)))
  return (
    <Panel title="Signaux dominants" aside={<span className="text-xs text-mute-2">z-score</span>}>
      {feats.length ? (
        <ul className="flex flex-col gap-3">
          {feats.map((f) => (
            <li key={f.name} className="flex flex-col gap-1.5">
              <div className="flex justify-between gap-2 font-mono text-xs">
                <span className="break-all text-fg-2">{f.name}</span>
                <span className={f.z >= 0 ? 'text-accent' : 'text-info'}>
                  {f.z > 0 ? '+' : ''}
                  {f.z.toFixed(1)}σ
                </span>
              </div>
              <div className="h-1.5 overflow-hidden rounded-[3px] bg-edge-2" aria-hidden>
                <div className={`h-full rounded-[3px] ${f.z >= 0 ? 'bg-accent' : 'bg-info'}`} style={{ width: `${((Math.abs(f.z) / maxZ) * 100).toFixed(0)}%` }} />
              </div>
              <span className="text-[11px] text-mute-3">valeur observée {f.value.toLocaleString('fr-FR')}</span>
            </li>
          ))}
        </ul>
      ) : (
        <span className="text-[13px] text-mute-3">Disponibles à la détection d'une anomalie.</span>
      )}
    </Panel>
  )
}

export function PlaybooksPanel({ incident }: { incident: Incident | null }) {
  return (
    <Panel title="Playbooks de décision" subtitle="remediation/decision_table.yml">
      <ul className="flex flex-col gap-2">
        {PLAYBOOKS.map((p) => {
          const active = incident?.incidentType === p.type
          return (
            <li
              key={p.type}
              data-playbook={p.type}
              data-active={active}
              className={`flex flex-col gap-1.5 rounded-[11px] border px-3 py-[11px] ${active ? 'border-accent bg-accent/8' : 'border-edge bg-card-2'}`}
            >
              <span className="flex items-center justify-between gap-2">
                <span className={`font-mono text-xs ${active ? 'text-accent-2' : 'text-fg-2'}`}>{p.type}</span>
                <span className="text-[11px] text-mute-3">{p.nature}</span>
              </span>
              <span className="text-xs text-mute">{p.actions.join(' + ')}</span>
            </li>
          )
        })}
      </ul>
    </Panel>
  )
}

export function EvidencePanel({ incident, grafanaBase }: { incident: Incident | null; grafanaBase: string }) {
  const ev = incident?.anomaly?.evidence
  const items = [
    ev?.prometheus_query && { label: 'Prometheus', q: ev.prometheus_query, href: exploreLink(grafanaBase, 'prometheus', ev.prometheus_query) },
    ev?.loki_query && { label: 'Loki', q: ev.loki_query, href: exploreLink(grafanaBase, 'loki', ev.loki_query) },
  ].filter((x): x is { label: string; q: string; href: string } => Boolean(x))
  if (!items.length) return null
  return (
    <Panel title="Preuves">
      {items.map((e) => (
        <a
          key={e.label}
          href={e.href}
          target="_blank"
          rel="noopener noreferrer"
          className="flex flex-col gap-1 rounded-[10px] border border-edge bg-card-2 px-3 py-2.5 hover:border-[#3f3f46]"
        >
          <span className="text-xs text-accent-2">{e.label} ↗</span>
          <span className="break-all font-mono text-[11px] text-mute-2">{e.q}</span>
        </a>
      ))}
    </Panel>
  )
}
