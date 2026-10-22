import { useEffect, useRef, type HTMLAttributes, type ReactNode } from 'react'
import { ApiError } from '../api/errors'
import { accountGradient, accountName, maskCard, signed, type TxView } from '../lib/bank'
import { userMessage } from '../lib/errorMessages'
import { formatMoney, formatTime } from '../lib/format'
import type { Account } from '../types/api'
import { Icon, Logo, type IconName } from './icons'

export function Brand({ inverted = false }: { inverted?: boolean }) {
  return (
    <div className="flex items-center gap-2.5">
      <div
        aria-hidden
        className={`grid h-[34px] w-[34px] place-items-center rounded-[11px] text-base font-bold ${inverted ? 'bg-white text-ink' : 'bg-night text-white'}`}
      >
        <Logo size={20} />
      </div>
      <span className="text-[17px] font-semibold tracking-[-0.02em]">Résilience</span>
    </div>
  )
}

export function Card({ children, className = '', ...rest }: { children: ReactNode; className?: string } & HTMLAttributes<HTMLElement>) {
  return (
    <section className={`card flex flex-col ${className}`} {...rest}>
      {children}
    </section>
  )
}

export function H2({ id, children, className = '' }: { id?: string; children: ReactNode; className?: string }) {
  return (
    <h2 id={id} className={`m-0 text-[17px] font-semibold ${className}`}>
      {children}
    </h2>
  )
}

/** Squelettes de chargement (maquette : cartes + liste). */
export function LoadingState({ label = 'Chargement' }: { label?: string }) {
  return (
    <div role="status" aria-busy="true" aria-label={label} className="flex flex-col gap-4">
      <div className="flex gap-3.5 overflow-hidden">
        <div className="h-[156px] w-[272px] flex-none animate-sk rounded-3xl bg-[#dfe1e5]" />
        <div className="h-[156px] w-[272px] flex-none animate-sk rounded-3xl bg-[#e6e8eb]" />
      </div>
      <div className="flex flex-col gap-3.5 rounded-3xl bg-white p-4">
        {[1, 2, 3, 4].map((k) => (
          <div key={k} className="flex items-center gap-3">
            <div className="h-11 w-11 animate-sk rounded-[14px] bg-[#e6e8eb]" />
            <div className="flex flex-1 flex-col gap-2">
              <div className="h-3 w-[55%] animate-sk rounded-md bg-[#e6e8eb]" />
              <div className="h-2.5 w-[35%] animate-sk rounded-md bg-[#eef0f2]" />
            </div>
            <div className="h-3 w-16 animate-sk rounded-md bg-[#e6e8eb]" />
          </div>
        ))}
      </div>
    </div>
  )
}

export function EmptyState({ title, text, icon = 'grid' }: { title: string; text: string; icon?: IconName }) {
  return (
    <div className="flex flex-col items-center gap-3 rounded-[28px] bg-white px-6 py-12 text-center">
      <div className="grid h-16 w-16 place-items-center rounded-[22px] bg-[#eef0f2] text-ink-2">
        <Icon name={icon} size={28} />
      </div>
      <h2 className="m-0 text-xl font-semibold">{title}</h2>
      <p className="m-0 max-w-[340px] text-pretty text-[15px] leading-normal text-ink-3">{text}</p>
    </div>
  )
}

/** Erreur de chargement : message utilisateur + référence (request_id) + Réessayer. */
export function ErrorState({ error, onRetry, title = 'Impossible de charger les données' }: { error: unknown; onRetry?: () => void; title?: string }) {
  const requestId = error instanceof ApiError ? error.requestId : null
  return (
    <div role="alert" className="flex flex-col items-center gap-3 rounded-[28px] bg-white px-6 py-12 text-center">
      <div className="grid h-16 w-16 place-items-center rounded-[22px] bg-warn-bg text-warn-fg">
        <Icon name="alert" size={28} />
      </div>
      <h2 className="m-0 text-xl font-semibold">{title}</h2>
      <p className="m-0 max-w-[360px] text-[15px] leading-normal text-ink-3">
        {userMessage(error)} Aucune opération n'a été perdue.
        {requestId && <span className="mt-1 block font-mono text-xs">Réf. {requestId}</span>}
      </p>
      {onRetry && (
        <button type="button" onClick={onRetry} className="btn-primary mt-2 h-[52px] px-7">
          Réessayer
        </button>
      )}
    </div>
  )
}

export function Alert({ tone = 'ko', children }: { tone?: 'ko' | 'warn' | 'info'; children: ReactNode }) {
  const cls = { ko: 'bg-ko-bg text-ko-fg', warn: 'bg-warn-bg text-warn-fg', info: 'bg-mute text-ink' }[tone]
  return (
    <div role={tone === 'ko' ? 'alert' : 'status'} className={`rounded-[14px] px-4 py-3 text-sm font-medium ${cls}`}>
      {children}
    </div>
  )
}

export function AccountCard({
  account,
  index,
  selected,
  size = 'lg',
  onClick,
}: {
  account: Account
  index: number
  selected?: boolean
  size?: 'lg' | 'md' | 'sm'
  onClick?: () => void
}) {
  const dims = { lg: 'h-[156px] w-[272px] p-5', md: 'h-[142px] w-[250px] p-[18px]', sm: 'h-[116px] w-[210px] p-4 rounded-[20px]' }[size]
  const amount = { lg: 'text-2xl', md: 'text-[22px]', sm: 'text-xl' }[size]
  const name = accountName(account.id)
  // Sélection dessinée DANS la carte (ombre inset) : un outline extérieur était rogné par le carrousel défilant.
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={selected === undefined ? undefined : selected}
      aria-label={`${name}, solde ${formatMoney(account.balance, account.currency)}`}
      style={{ background: accountGradient(index) }}
      className={`relative flex flex-none snap-start flex-col justify-between overflow-hidden rounded-3xl border-0 text-left text-white outline-offset-[3px] ${dims} ${
        selected ? 'shadow-[inset_0_0_0_3px_var(--color-violet),0_18px_30px_-18px_rgba(18,19,22,.65)]' : 'shadow-[0_18px_30px_-18px_rgba(18,19,22,.65)]'
      }`}
    >
      <span aria-hidden className="absolute -top-[70px] -right-[50px] h-[210px] w-[210px] rounded-full border border-white/10" />
      <span aria-hidden className="absolute -top-[30px] -right-2.5 h-[130px] w-[130px] rounded-full border border-white/[.07]" />
      <span className="relative flex items-start justify-between gap-3">
        <span className="flex flex-col gap-1">
          <span className="text-[13px] font-medium text-ink-4">{name}</span>
          <span className={`tnum font-semibold tracking-[-0.02em] ${amount}`}>{formatMoney(account.balance, account.currency)}</span>
        </span>
        {size === 'lg' && <span className="grid h-[30px] w-[30px] flex-none place-items-center rounded-[10px] bg-white text-ink"><Logo size={18} /></span>}
      </span>
      <span className="relative flex items-center justify-between">
        <span className="font-mono text-[13px] tracking-[0.05em] text-[#e4e6e9]">{maskCard(account)}</span>
        {size === 'lg' && <span className="text-xs text-ink-4">{account.currency}</span>}
      </span>
    </button>
  )
}

const TX_ICON: Record<TxView['direction'], IconName> = { out: 'outArrow', in: 'inArrow', internal: 'swap' }
const TX_TONE: Record<TxView['direction'], string> = {
  out: 'bg-[#eceef1] text-ink',
  in: 'bg-ok-bg text-ok-fg',
  internal: 'bg-[#d8f2f7] text-[#0e6b80]',
}

export function TxRow({ view, onOpen }: { view: TxView; onOpen: () => void }) {
  const { tx, rejected, delta, direction } = view
  const color = rejected ? 'text-ink-3 line-through' : delta > 0 ? 'text-ok-fg' : 'text-ink'
  const amount = direction === 'internal' ? formatMoney(tx.amount, tx.currency) : signed(delta, tx.currency)
  const time = formatTime(tx.createdAt)
  return (
    <button
      type="button"
      onClick={onOpen}
      className="flex min-h-16 w-full items-center gap-3 rounded-2xl border-0 bg-transparent px-2 py-2.5 text-left hover:bg-page"
    >
      <span className={`grid h-11 w-11 flex-none place-items-center rounded-[14px] ${TX_TONE[direction]}`}>
        <Icon name={rejected ? 'x' : TX_ICON[direction]} />
      </span>
      <span className="flex min-w-0 flex-1 flex-col gap-0.5">
        <span className="truncate text-[15px] font-semibold">{view.title}</span>
        <span className="truncate text-[13px] text-ink-3">
          {view.counterpart}
          {time && ` · ${time}`}
        </span>
      </span>
      <span className="flex flex-none flex-col items-end gap-1">
        <span className={`tnum text-[15px] font-semibold ${color}`}>{amount}</span>
        {rejected && <span className="rounded-full bg-ko-bg px-2 py-[3px] text-[11px] font-bold text-ko-fg">Refusé</span>}
      </span>
    </button>
  )
}

export function Segmented<T extends string>({
  label,
  options,
  value,
  onChange,
  stretch = false,
  className = 'bg-mute',
}: {
  label: string
  options: readonly (readonly [T, string])[]
  value: T
  onChange: (v: T) => void
  stretch?: boolean
  className?: string
}) {
  return (
    <div role="group" aria-label={label} className={`flex gap-1 rounded-[14px] p-[3px] ${className}`}>
      {options.map(([v, l]) => (
        <button
          key={v}
          type="button"
          aria-pressed={v === value}
          onClick={() => onChange(v)}
          className={`min-h-11 rounded-[11px] border-0 px-3.5 text-sm font-semibold ${stretch ? 'flex-1' : ''} ${v === value ? 'bg-night text-white' : 'bg-transparent text-ink-2'}`}
        >
          {l}
        </button>
      ))}
    </div>
  )
}

export function Avatar({ text, index, size = 56 }: { text: string; index: number; size?: number }) {
  const tones = ['bg-[#dde9ff] text-[#1d4fb8]', 'bg-[#fde2ef] text-[#a3195b]', 'bg-[#d9f4ea] text-[#0f7a55]', 'bg-[#ffe8d6] text-[#b24a00]', 'bg-[#ebe3ff] text-[#5b34c4]', 'bg-[#fff3c4] text-[#8a6400]']
  return (
    <span
      aria-hidden
      style={{ width: size, height: size, fontSize: Math.round(size * 0.29) }}
      className={`grid flex-none place-items-center rounded-full font-semibold ${tones[index % tones.length]}`}
    >
      {text}
    </span>
  )
}

/** Boîte de confirmation (maquette : bas d'écran sur mobile, centrée sur desktop). */
export function ConfirmDialog({
  title,
  text,
  confirmLabel,
  icon,
  danger = false,
  onConfirm,
  onCancel,
}: {
  title: string
  text: string
  confirmLabel: string
  icon: IconName
  danger?: boolean
  onConfirm: () => void
  onCancel: () => void
}) {
  const cancelRef = useRef<HTMLButtonElement>(null)
  const cancel = useRef(onCancel)
  useEffect(() => {
    cancel.current = onCancel
  })
  useEffect(() => {
    cancelRef.current?.focus()
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && cancel.current()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-[rgba(18,19,22,.5)] p-3 lg:items-center lg:p-6">
      <div role="alertdialog" aria-modal="true" aria-labelledby="dlg-title" className="flex w-full max-w-[440px] flex-col gap-3.5 rounded-[28px] bg-white p-6 shadow-[0_30px_60px_-20px_rgba(18,19,22,.5)]">
        <span className="grid h-[52px] w-[52px] place-items-center rounded-2xl bg-page">
          <Icon name={icon} size={28} />
        </span>
        <h2 id="dlg-title" className="m-0 text-[21px] font-bold tracking-[-0.02em]">
          {title}
        </h2>
        <p className="m-0 text-[15px] leading-normal text-ink-2">{text}</p>
        <div className="mt-1.5 grid grid-cols-2 gap-2.5">
          <button ref={cancelRef} type="button" onClick={onCancel} className="btn-ghost h-[52px] text-[15px]">
            Annuler
          </button>
          <button type="button" onClick={onConfirm} className={`btn-primary h-[52px] text-[15px] ${danger ? 'bg-ko-fg hover:bg-ko-fg' : ''}`}>
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  )
}
