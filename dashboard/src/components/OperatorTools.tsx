import { useState, type FormEvent } from 'react'
import { ASSISTANT_API, MANUAL_ACTIONS_URL } from '../config'
import { operatorAuthHeader, operatorErrorMessage, operatorOutcome, readOperatorToken, saveOperatorToken } from '../lib/operatorToken'
import type { Incident } from '../types/events'
import { OperatorTokenForm } from './OperatorTokenForm'
import { Panel, Pill } from './Panel'

/** Erreur HTTP lisible ; `status` conservé pour distinguer 401/403/503 (jeton opérateur). */
export class HttpError extends Error {
  constructor(
    message: string,
    readonly status: number | null,
  ) {
    super(message)
  }
}

/** POST JSON ; lève une HttpError lisible (`code : message` du format d'erreur commun, sinon HTTP xxx). */
export async function postJson<T>(url: string, body: unknown, headers: Record<string, string> = {}): Promise<T> {
  let r: Response
  try {
    r = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json', ...headers }, body: JSON.stringify(body) })
  } catch {
    throw new HttpError('Service injoignable', null)
  }
  const j = (await r.json().catch(() => null)) as { error?: { code?: string; message?: string } } | null
  if (!r.ok) throw new HttpError(j?.error ? `${j.error.code ?? 'erreur'} : ${j.error.message ?? ''}` : `HTTP ${r.status}`, r.status)
  if (j === null) throw new HttpError('Réponse invalide', r.status)
  return j as T
}

const btn = 'h-[34px] cursor-pointer rounded-full border border-[#333339] px-3.5 text-[13px] hover:bg-[#1b1b1e] disabled:cursor-not-allowed disabled:opacity-50'
const box = 'rounded-xl border border-edge bg-card-2 px-3.5 py-3 text-[13px]'

type Summary = { summary: string; degraded: boolean }

/** Résumé DSI (à la demande, mis en cache par incident) + export du post-mortem en .md. */
export function IncidentReportPanel({ incident }: { incident: Incident | null }) {
  const [cache, setCache] = useState<Record<string, Summary>>({})
  const [busy, setBusy] = useState<'summary' | 'postmortem' | null>(null)
  const [error, setError] = useState<string | null>(null)
  const closed = incident !== null && (incident.verification !== null || incident.failure !== null)
  const summary = incident ? cache[incident.id] : undefined

  const run = async (kind: 'summary' | 'postmortem') => {
    if (!incident) return
    setBusy(kind)
    setError(null)
    try {
      if (kind === 'summary') {
        const r = await postJson<Summary>(`${ASSISTANT_API}/summarize`, { incident })
        setCache((c) => ({ ...c, [incident.id]: { summary: r.summary, degraded: r.degraded } }))
      } else {
        const r = await postJson<{ markdown: string }>(`${ASSISTANT_API}/postmortem`, { incident })
        const href = URL.createObjectURL(new Blob([r.markdown], { type: 'text/markdown' }))
        const a = document.createElement('a')
        a.href = href
        a.download = `postmortem-${incident.id}.md`
        a.click()
        URL.revokeObjectURL(href)
      }
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(null)
    }
  }

  return (
    <Panel title="Rapport d'incident" subtitle="généré par l'assistant, à la demande">
      <div className="flex flex-wrap gap-2">
        <button type="button" className={btn} disabled={!incident || busy !== null} onClick={() => run('summary')}>
          {busy === 'summary' ? 'Résumé en cours…' : 'Résumé pour la direction'}
        </button>
        <button
          type="button"
          className={btn}
          disabled={!closed || busy !== null}
          title={closed ? undefined : 'Disponible une fois l’incident terminé'}
          onClick={() => run('postmortem')}
        >
          {busy === 'postmortem' ? 'Génération…' : 'Générer le post-mortem'}
        </button>
      </div>
      <div aria-live="polite" className="flex flex-col gap-2">
        {error && <p role="alert" className="text-[13px] text-ko">Échec : {error}</p>}
        {summary && (
          <div className={box}>
            {summary.degraded && <Pill tone="warn" className="mb-2 inline-block">mode dégradé</Pill>}
            <p className="whitespace-pre-wrap">{summary.summary}</p>
          </div>
        )}
      </div>
    </Panel>
  )
}

interface Proposal {
  action: string
  params: Record<string, string>
  explanation: string
}
type ManualResult = { incident_id: string; action: string; status: string; detail: string | null }

/**
 * Commande en langage naturel -> proposition de l'assistant -> exécution UNIQUEMENT après « Confirmer ».
 * L'exécution est une écriture : jeton OPÉRATEUR (REMEDIATION_OPERATOR_TOKEN) demandé à la première
 * confirmation, gardé en sessionStorage, effacé sur 401/403. L'assistant ne voit jamais ce jeton.
 */
export function OperatorCommandPanel() {
  const [command, setCommand] = useState('')
  const [reason, setReason] = useState('')
  const [proposal, setProposal] = useState<Proposal | null>(null)
  const [info, setInfo] = useState<string | null>(null)
  const [result, setResult] = useState<ManualResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [askToken, setAskToken] = useState(false)

  const clear = () => {
    setProposal(null)
    setInfo(null)
    setResult(null)
    setError(null)
    setAskToken(false)
  }

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    clear()
    setBusy(true)
    try {
      const r = await postJson<{ proposal: Proposal | null; message: string }>(`${ASSISTANT_API}/propose`, { command: command.trim() })
      setProposal(r.proposal)
      setInfo(r.proposal ? null : r.message)
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const execute = async (token: string) => {
    if (!proposal) return
    setBusy(true)
    setError(null)
    try {
      const body = { action: proposal.action, params: proposal.params, ...(reason.trim() ? { reason: reason.trim() } : {}) }
      setResult(await postJson<ManualResult>(MANUAL_ACTIONS_URL, body, operatorAuthHeader(token)))
      setProposal(null)
    } catch (err) {
      const status = err instanceof HttpError ? err.status : null
      const outcome = status === null ? 'error' : operatorOutcome(status) // 401/403 : jeton oublié
      setError(outcome === 'unauthorized' || outcome === 'forbidden' || outcome === 'unavailable'
        ? operatorErrorMessage(outcome, 'Action')
        : (err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const confirm = () => {
    const token = readOperatorToken()
    if (token) void execute(token)
    else setAskToken(true)
  }

  const submitToken = (token: string) => {
    setAskToken(false)
    saveOperatorToken(token)
    void execute(token)
  }

  return (
    <Panel title="Commande opérateur" subtitle="proposition de l'assistant, exécutée seulement après confirmation">
      <form onSubmit={submit} className="flex flex-col gap-2">
        <label htmlFor="op-command" className="text-xs text-mute-2">
          Commande
        </label>
        <input
          id="op-command"
          value={command}
          onChange={(e) => setCommand(e.target.value)}
          placeholder="ex. bloque l'IP 192.168.137.50"
          minLength={3}
          maxLength={300}
          required
          className="h-[34px] rounded-lg border border-edge bg-card-2 px-3 text-[13px]"
        />
        <button type="submit" className={`${btn} self-start`} disabled={busy || command.trim().length < 3}>
          Proposer
        </button>
      </form>
      <div aria-live="polite" className="flex flex-col gap-2">
        {info && <p className="text-[13px] text-mute">{info}</p>}
        {error && <p role="alert" className="text-[13px] text-ko">Échec : {error}</p>}
        {proposal && (
          <div className={`${box} flex flex-col gap-2`}>
            <span className="font-mono text-xs">
              {proposal.action} · {Object.entries(proposal.params).map(([k, v]) => `${k}=${v}`).join(' · ')}
            </span>
            <p>{proposal.explanation}</p>
            <label htmlFor="op-reason" className="text-xs text-mute-2">
              Motif (optionnel)
            </label>
            <input
              id="op-reason"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              maxLength={200}
              className="h-[34px] rounded-lg border border-edge bg-card px-3 text-[13px]"
            />
            {askToken && (
              <OperatorTokenForm action={`exécuter ${proposal.action}`} onSubmit={submitToken} onCancel={() => setAskToken(false)} />
            )}
            <div className="flex gap-2">
              <button type="button" className={btn} disabled={busy || askToken} onClick={confirm}>
                {busy ? 'Exécution…' : 'Confirmer'}
              </button>
              <button type="button" className={btn} disabled={busy} onClick={clear}>
                Annuler
              </button>
            </div>
          </div>
        )}
        {result && (
          <p className="text-[13px]">
            <Pill tone={result.status === 'ok' ? 'ok' : result.status === 'dry_run' ? 'info' : 'ko'}>{result.status}</Pill>{' '}
            {result.action} — {result.detail ?? '—'} <span className="font-mono text-[11px] text-mute-3">{result.incident_id}</span>
          </p>
        )}
      </div>
    </Panel>
  )
}
