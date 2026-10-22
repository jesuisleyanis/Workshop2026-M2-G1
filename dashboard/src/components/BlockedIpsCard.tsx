import type { BlockedIpsState } from '../hooks/useBlockedIps'
import { formatTime } from '../lib/format'
import { Panel, Pill, type Tone } from './Panel'

const LIST_UI: Record<'temporary' | 'permanent' | 'unknown', { text: string; tone: Tone }> = {
  temporary: { text: 'Temporaire', tone: 'warn' },
  permanent: { text: 'Permanente', tone: 'ko' },
  unknown: { text: 'Hors moteur', tone: 'mute' },
}

/** Carte « IP bloquées » : liste noire réellement appliquée par le WAF (lecture seule). */
export function BlockedIpsCard({ items, error }: BlockedIpsState) {
  const aside =
    items === null ? (
      <span className="text-xs text-mute-2">{error ? 'moteur injoignable' : 'chargement…'}</span>
    ) : (
      <span className="text-xs text-mute-2">
        {items.length} IP{items.length > 1 ? 's' : ''}
        {error ? ' · dernière liste connue' : ''}
      </span>
    )
  return (
    <Panel title="IP bloquées" subtitle="Liste noire du WAF (remédiation)" aside={aside}>
      {items !== null && items.length === 0 ? (
        <p className="text-[13px] text-mute-2">Aucune IP bloquée.</p>
      ) : (
        <ul className="flex flex-col">
          {(items ?? []).map((b) => {
            const ui = LIST_UI[b.list]
            return (
              <li key={b.ip} data-ip={b.ip} className="flex items-center justify-between gap-3 border-b border-[#1f1f23] py-[9px] last:border-b-0">
                <span className="flex min-w-0 flex-col gap-0.5">
                  <span className="font-mono text-[13px]">{b.ip}</span>
                  <span className="text-xs text-mute-2">
                    {b.incidentType ? `${b.incidentType} · ` : ''}
                    {b.blockedAt ? `bloquée à ${formatTime(b.blockedAt)}` : 'ajoutée hors moteur'}
                  </span>
                </span>
                <Pill tone={ui.tone}>{ui.text}</Pill>
              </li>
            )
          })}
        </ul>
      )}
    </Panel>
  )
}
