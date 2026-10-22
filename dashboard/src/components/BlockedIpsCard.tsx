import { useState } from 'react'
import type { BlockedIpsState } from '../hooks/useBlockedIps'
import { formatTime } from '../lib/format'
import { operatorErrorMessage, readOperatorToken, saveOperatorToken, type OperatorOutcome } from '../lib/operatorToken'
import { OperatorTokenForm } from './OperatorTokenForm'
import { Panel, Pill, type Tone } from './Panel'

const LIST_UI: Record<'temporary' | 'permanent' | 'unknown', { text: string; tone: Tone }> = {
  temporary: { text: 'Temporaire', tone: 'warn' },
  permanent: { text: 'Permanente', tone: 'ko' },
  unknown: { text: 'Hors moteur', tone: 'mute' },
}

interface Props extends BlockedIpsState {
  /** Débloque l'IP avec le jeton OPÉRATEUR ; absent = carte en lecture seule. */
  onUnblock?: (ip: string, operatorToken: string) => Promise<OperatorOutcome>
  /** Confirmation avant déblocage (injectable pour les tests). */
  confirm?: (message: string) => boolean
}

/**
 * Carte « IP bloquées » : liste noire réellement appliquée par le WAF, déblocage par IP.
 * Le déblocage est une écriture : jeton OPÉRATEUR demandé au premier usage (sessionStorage), effacé sur 401/403.
 */
export function BlockedIpsCard({ items, error, onUnblock, confirm = (m) => window.confirm(m) }: Props) {
  const [pending, setPending] = useState<string | null>(null)
  const [failed, setFailed] = useState<string | null>(null)
  const [asking, setAsking] = useState<string | null>(null) // IP en attente de saisie du jeton

  const run = async (ip: string, token: string) => {
    if (!onUnblock) return
    setPending(ip)
    setFailed(null)
    const outcome = await onUnblock(ip, token)
    setPending(null)
    if (outcome !== 'ok') setFailed(operatorErrorMessage(outcome, `Déblocage de ${ip}`))
  }

  const unblock = (ip: string) => {
    if (!onUnblock || !confirm(`Débloquer ${ip} ? Ses requêtes seront de nouveau acceptées par le WAF.`)) return
    setFailed(null)
    const token = readOperatorToken()
    if (token) void run(ip, token)
    else setAsking(ip)
  }

  const submitToken = (token: string) => {
    const ip = asking
    setAsking(null)
    saveOperatorToken(token)
    if (ip) void run(ip, token)
  }

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
      {failed && (
        <p role="alert" className="text-xs text-ko">
          {failed}
        </p>
      )}
      {asking && <OperatorTokenForm action={`débloquer ${asking}`} onSubmit={submitToken} onCancel={() => setAsking(null)} />}
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
                <span className="flex items-center gap-2">
                  <Pill tone={ui.tone}>{ui.text}</Pill>
                  {onUnblock && (
                    <button
                      type="button"
                      onClick={() => unblock(b.ip)}
                      disabled={pending !== null || asking !== null}
                      aria-label={`Débloquer ${b.ip}`}
                      className="h-[26px] cursor-pointer rounded-full border border-[#333339] px-2.5 text-xs hover:bg-[#1b1b1e] disabled:cursor-wait disabled:opacity-50"
                    >
                      {pending === b.ip ? 'Déblocage…' : 'Débloquer'}
                    </button>
                  )}
                </span>
              </li>
            )
          })}
        </ul>
      )}
    </Panel>
  )
}
