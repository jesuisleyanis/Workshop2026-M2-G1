import type { ReactNode } from 'react'
import { ApiError } from '../api/errors'
import { userMessage } from '../lib/errorMessages'
import { formatDate, formatDateShort, formatMoney, formatTime, shortIban } from '../lib/format'
import type { Account, Transaction } from '../types/api'

export function ErrorBlock({ title, error, onRetry }: { title: string; error: unknown; onRetry?: () => void }) {
  const requestId = error instanceof ApiError ? error.requestId : null
  return (
    <div role="alert" className="flex flex-col gap-3 rounded-2xl bg-ko-bg p-4 text-ko-fg">
      <span className="text-[15px] font-semibold">{title}</span>
      <span className="text-[13px] leading-snug">
        {userMessage(error)}
        {requestId && ` (réf. ${requestId})`}
      </span>
      {onRetry && (
        <button type="button" onClick={onRetry} className="h-10 cursor-pointer self-start rounded-[11px] bg-ko-fg px-4 font-semibold text-white">
          Réessayer
        </button>
      )}
    </div>
  )
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="rounded-2xl border-[1.5px] border-dashed border-[#dfe2e6] p-6 text-center text-sm text-ink-3">{children}</div>
}

export function Skeleton({ className = '', label }: { className?: string; label?: string }) {
  return (
    <div role={label ? 'status' : undefined} aria-label={label} className={`animate-pulse rounded-xl bg-[#eceef1] ${className}`} />
  )
}

/** Plusieurs squelettes regroupés sous un seul libellé accessible. */
export function Loading({ label, count, className }: { label: string; count: number; className: string }) {
  return (
    <div role="status" aria-label={label} className="flex flex-col gap-2.5">
      {Array.from({ length: count }, (_, i) => (
        <Skeleton key={i} className={className} />
      ))}
    </div>
  )
}

export function StatusPill({ status }: { status: Transaction['status'] }) {
  const rejected = status === 'rejected'
  return (
    <span className={`rounded-md px-2 py-0.5 text-[11px] ${rejected ? 'bg-ko-bg text-ko-fg' : 'bg-ok-bg text-ok-fg'}`}>
      {rejected ? 'Rejeté' : 'Effectué'}
    </span>
  )
}

export function Brand({ inverted = false }: { inverted?: boolean }) {
  return (
    <div className="flex items-center gap-2.5">
      <div
        className={`grid h-8 w-8 place-items-center rounded-[10px] text-base font-bold ${inverted ? 'bg-[#f3f4f6] text-night' : 'bg-night text-white'}`}
        aria-hidden
      >
        R
      </div>
      <span className="text-[17px] font-semibold tracking-tight">Résilience</span>
    </div>
  )
}

export type Tone = 'ok' | 'ko' | 'neutral'
export const iconTone: Record<Tone, string> = { ko: 'bg-ko-bg text-[#b23a26]', ok: 'bg-ok-bg text-ok-fg', neutral: 'bg-[#eceef1] text-ink' }
export const amountTone: Record<Tone, string> = { ko: 'text-ink-4 line-through', ok: 'text-ok-fg', neutral: 'text-ink' }

/** Présentation d'une transaction du point de vue de l'utilisateur (sens, signe, libellé). */
export function txView(t: Transaction, mine: Map<string, Account>, label?: string | null) {
  const out = mine.has(t.fromAccount)
  const inc = mine.has(t.toAccount)
  const internal = out && inc
  const rejected = t.status === 'rejected'
  const sign = rejected || internal ? '' : out ? '− ' : '+ '
  const dst = mine.get(t.toAccount)
  const tone: Tone = rejected ? 'ko' : !out && inc ? 'ok' : 'neutral'
  return {
    title: internal ? 'Virement interne' : out ? `Vers le compte #${t.toAccount}` : `Reçu du compte #${t.fromAccount}`,
    sub: label || (internal ? `#${t.fromAccount} → #${t.toAccount}` : out ? `Depuis #${t.fromAccount}` : `Sur #${t.toAccount}`),
    dstDetail: dst?.iban ? `${shortIban(dst.iban)} · vous` : `Réf. #${t.id}`,
    date: formatDate(t.createdAt),
    dateShort: formatDateShort(t.createdAt),
    time: formatTime(t.createdAt),
    amount: sign + formatMoney(t.amount, t.currency),
    glyph: rejected ? '×' : internal ? '⇄' : out ? '↗' : '↙',
    tone,
  }
}

export function accountMap(accounts: Account[] | null): Map<string, Account> {
  return new Map((accounts ?? []).map((a) => [a.id, a]))
}
