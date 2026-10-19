import { useState, type FormEvent } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { api } from '../api'
import { ApiError } from '../api/errors'
import { Empty, ErrorBlock } from '../components/ui'
import { useBankData } from '../hooks/useBankData'
import { userMessage } from '../lib/errorMessages'
import { amountToInput, formatDateTime, formatMoney, shortIban } from '../lib/format'
import { parseAmount, validateTransfer } from '../lib/validation'
import type { Account, Transaction } from '../types/api'

/** Pré-sélection du compte à débiter (depuis la page Comptes). */
export interface TransferRouteState {
  fromAccount?: string
}

type Result =
  | { kind: 'done'; tx: Transaction }
  | { kind: 'refused'; error: ApiError; from: string; to: string; amount: number; currency: string }

export function TransferPage() {
  const { accounts } = useBankData()

  if (accounts.loading && !accounts.data) {
    return (
      <div role="status" className="grid h-56 place-items-center rounded-[18px] bg-[#f2f3f5] text-sm text-ink-3">
        Chargement de vos comptes…
      </div>
    )
  }
  if (accounts.error) return <ErrorBlock title="Impossible de charger vos comptes" error={accounts.error} onRetry={accounts.reload} />
  if (!accounts.data?.length) return <Empty>Aucun compte à débiter : impossible d'émettre un virement.</Empty>
  return <TransferForm accounts={accounts.data} />
}

function TransferForm({ accounts }: { accounts: Account[] }) {
  const { accounts: accountsRes, transactions, saveLabel } = useBankData()
  const prefill = (useLocation().state as TransferRouteState | null)?.fromAccount
  const [fromId, setFromId] = useState(() => (accounts.some((a) => a.id === prefill) ? prefill! : accounts[0]!.id))
  const [to, setTo] = useState('')
  const [amount, setAmount] = useState('')
  const [label, setLabel] = useState('')
  const [attempted, setAttempted] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [apiError, setApiError] = useState<unknown>(null)
  const [result, setResult] = useState<Result | null>(null)

  const mine = new Map(accounts.map((a) => [a.id, a]))
  const src = mine.get(fromId) ?? accounts[0]!
  const errors = validateTransfer({ fromAccount: src.id, toAccount: to, amount, balance: src.balance })
  const value = errors.amount ? null : parseAmount(amount)
  const toId = /^\d+$/.test(to.trim()) ? String(Number(to.trim())) : null
  const after = value !== null ? src.balance - value : null

  // Raccourcis bénéficiaire : mes autres comptes puis les derniers comptes externes crédités.
  const recent = [
    ...new Set((transactions.data ?? []).filter((t) => mine.has(t.fromAccount) && !mine.has(t.toAccount)).map((t) => t.toAccount)),
  ].slice(0, 4)
  const chips = [
    ...accounts.filter((a) => a.id !== src.id).map((a) => ({ id: a.id, label: `Mon compte #${a.id}` })),
    ...recent.map((id) => ({ id, label: `#${id} · récent` })),
  ]

  function refresh() {
    accountsRes.reload()
    transactions.reload()
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    setAttempted(true)
    setApiError(null)
    if (Object.keys(errors).length > 0 || value === null || toId === null || submitting) return

    setSubmitting(true)
    try {
      const tx = await api.createTransaction({ from_account: src.id, to_account: toId, amount: value })
      if (label.trim()) saveLabel(tx.id, label.trim())
      setResult({ kind: 'done', tx })
      refresh()
    } catch (err) {
      if (err instanceof ApiError && err.isUnauthorized) return // AuthProvider renvoie au login
      if (err instanceof ApiError && err.code === 'insufficient_funds') {
        setResult({ kind: 'refused', error: err, from: src.id, to: toId, amount: value, currency: src.currency })
        refresh()
      } else {
        setApiError(err)
      }
    } finally {
      setSubmitting(false)
    }
  }

  function reset() {
    setResult(null)
    setTo('')
    setAmount('')
    setLabel('')
    setAttempted(false)
    setApiError(null)
  }

  if (result) return <ResultCard result={result} currency={src.currency} onNew={reset} />

  const show = (k: keyof typeof errors) => (attempted ? errors[k] : undefined)

  return (
    <div className="grid items-start gap-7 [grid-template-columns:repeat(auto-fit,minmax(min(100%,340px),1fr))]">
      <form onSubmit={onSubmit} noValidate aria-label="Virement" className="flex min-w-0 flex-col gap-6">
        <fieldset className="flex flex-col gap-2.5">
          <legend className="mb-2.5 text-[13px] font-semibold">Compte à débiter</legend>
          <div className="grid gap-2.5 [grid-template-columns:repeat(auto-fill,minmax(200px,1fr))]">
            {accounts.map((a) => {
              const selected = a.id === src.id
              return (
                <button
                  key={a.id}
                  type="button"
                  aria-pressed={selected}
                  aria-label={`Débiter le compte #${a.id}`}
                  onClick={() => {
                    setFromId(a.id)
                    setApiError(null)
                  }}
                  className={`flex min-h-[84px] cursor-pointer flex-col gap-1.5 rounded-2xl border-[1.5px] px-4 py-3.5 text-left ${selected ? 'border-night bg-night text-white' : 'border-line bg-white'}`}
                >
                  <span className="flex justify-between gap-2 text-[13px]">
                    <b>#{a.id}</b>
                    {a.iban && <span className="font-mono text-[11px] opacity-75">{shortIban(a.iban)}</span>}
                  </span>
                  <span className="tnum text-xl font-semibold tracking-tight">{formatMoney(a.balance, a.currency)}</span>
                </button>
              )
            })}
          </div>
          {show('fromAccount') && <span className="text-[13px] text-[#b23a26]">{errors.fromAccount}</span>}
        </fieldset>

        <div className="flex flex-col gap-2.5">
          <label htmlFor="to_account" className="text-[13px] font-semibold">Compte bénéficiaire</label>
          <input
            id="to_account"
            className="field font-mono"
            inputMode="numeric"
            autoComplete="off"
            placeholder="ex. 2001"
            aria-invalid={show('toAccount') ? true : undefined}
            aria-describedby={show('toAccount') ? 'to_account-err' : undefined}
            value={to}
            onChange={(e) => {
              setTo(e.target.value.replace(/\D/g, ''))
              setApiError(null)
            }}
          />
          {chips.length > 0 && (
            <div className="flex flex-wrap gap-2">
              {chips.map((c) => (
                <button
                  key={c.id}
                  type="button"
                  onClick={() => setTo(c.id)}
                  className={`h-[34px] cursor-pointer rounded-[10px] border-[1.5px] bg-white px-3 text-[13px] hover:border-night ${c.id === to ? 'border-night' : 'border-line'}`}
                >
                  {c.label}
                </button>
              ))}
            </div>
          )}
          {show('toAccount') && <span id="to_account-err" className="text-[13px] text-[#b23a26]">{errors.toAccount}</span>}
        </div>

        <div className="flex flex-col gap-2.5">
          <label htmlFor="amount" className="text-[13px] font-semibold">Montant</label>
          <div className="relative">
            <input
              id="amount"
              className="field tnum h-[68px] rounded-2xl pr-12 text-[30px] font-semibold"
              inputMode="decimal"
              autoComplete="off"
              placeholder="0,00"
              aria-invalid={show('amount') ? true : undefined}
              aria-describedby={show('amount') ? 'amount-err' : undefined}
              value={amount}
              onChange={(e) => {
                setAmount(e.target.value.replace(/[^\d.,\s]/g, ''))
                setApiError(null)
              }}
            />
            <span className="pointer-events-none absolute right-5 top-5 text-[22px] text-ink-3" aria-hidden>€</span>
          </div>
          <div className="flex flex-wrap justify-between gap-2.5 text-[13px] text-ink-3">
            <span>Disponible : {formatMoney(src.balance, src.currency)}</span>
            <button type="button" onClick={() => setAmount(amountToInput(src.balance))} className="cursor-pointer text-ink underline underline-offset-[3px]">
              Utiliser tout le solde
            </button>
          </div>
          {show('amount') && <span id="amount-err" className="text-[13px] text-[#b23a26]">{errors.amount}</span>}
        </div>

        <div className="flex flex-col gap-2.5">
          <label htmlFor="label" className="text-[13px] font-semibold">
            Libellé <span className="font-normal text-ink-3">(optionnel)</span>
          </label>
          <input id="label" className="field" maxLength={140} placeholder="ex. Remboursement dîner" value={label} onChange={(e) => setLabel(e.target.value)} />
          <span className="text-xs text-ink-4">Conservé dans votre historique sur cet appareil ; l'API ne reçoit pas ce champ.</span>
        </div>

        {apiError !== null && (
          <div role="alert" className="flex flex-col gap-1 rounded-[14px] bg-ko-bg px-4 py-3.5 text-ko-fg">
            <span className="text-sm font-semibold">Le virement n'a pas pu être émis</span>
            <span className="text-[13px] leading-snug">{userMessage(apiError)}</span>
            {apiError instanceof ApiError && (
              <span className="font-mono text-[11px] opacity-80">
                code={apiError.code}
                {apiError.requestId && ` · request_id=${apiError.requestId}`}
              </span>
            )}
          </div>
        )}

        <button type="submit" disabled={submitting} className="btn-primary h-14 rounded-[15px] text-base">
          {submitting ? 'Envoi en cours…' : value ? `Envoyer ${formatMoney(value, src.currency)}` : 'Envoyer le virement'}
        </button>
      </form>

      <aside aria-label="Récapitulatif" className="flex flex-col gap-4 rounded-[20px] bg-soft p-5">
        <span className="text-[17px] font-semibold tracking-tight">Récapitulatif</span>
        <dl className="flex flex-col">
          {[
            ['Depuis', src.iban ? `#${src.id} · ${shortIban(src.iban)}` : `#${src.id}`],
            ['Vers', toId ? `#${toId}${mine.has(toId) ? ' (votre compte)' : ''}` : '—'],
            ['Montant', value !== null ? formatMoney(value, src.currency) : '—'],
            ['Solde après', after !== null ? formatMoney(after, src.currency) : '—'],
            ['Libellé', label.trim() || '—'],
          ].map(([k, v]) => (
            <div key={k} className="flex justify-between gap-3.5 border-b border-[#e6e8ec] py-3 text-sm">
              <dt className="text-ink-3">{k}</dt>
              <dd className="tnum break-words text-right font-semibold">{v}</dd>
            </div>
          ))}
        </dl>
      </aside>
    </div>
  )
}

function ResultCard({ result, currency, onNew }: { result: Result; currency: string; onNew: () => void }) {
  const ok = result.kind === 'done' && result.tx.status === 'created'
  let title: string
  let text: string
  let rows: [string, string][]
  if (result.kind === 'refused') {
    title = 'Virement refusé'
    text = `${userMessage(result.error)} Aucun montant n'a été débité du compte #${result.from}.`
    rows = [
      ['Code', result.error.code],
      ['Montant demandé', formatMoney(result.amount, result.currency)],
      ['De', `#${result.from}`],
      ['Vers', `#${result.to}`],
      ['Référence requête', result.error.requestId ?? '—'],
    ]
  } else {
    const t = result.tx
    title = ok ? 'Virement accepté' : 'Virement rejeté'
    text = ok
      ? `${formatMoney(t.amount, currency)} ont été envoyés au compte #${t.toAccount}.`
      : 'Le serveur a enregistré la demande avec le statut « rejected ».'
    rows = [
      ['Référence', `#${t.id}`],
      ['Montant', formatMoney(t.amount, currency)],
      ['De', `#${t.fromAccount}`],
      ['Vers', `#${t.toAccount}`],
      ['Date', formatDateTime(t.createdAt)],
      ['Statut', t.status],
    ]
  }

  return (
    <div role={ok ? 'status' : 'alert'} className="flex max-w-[620px] flex-col gap-5 rounded-[22px] bg-soft p-[clamp(20px,3vw,32px)]">
      <div className="flex items-center gap-4">
        <div
          className={`grid h-14 w-14 flex-none place-items-center rounded-[18px] text-[26px] font-semibold ${ok ? 'bg-ok-bg text-ok-fg' : 'bg-ko-bg text-[#b23a26]'}`}
          aria-hidden
        >
          {ok ? '✓' : '×'}
        </div>
        <div className="flex flex-col gap-1">
          <span className="text-2xl font-semibold tracking-[-0.03em]">{title}</span>
          <span className="text-sm leading-snug text-ink-2">{text}</span>
        </div>
      </div>
      <div className="grid gap-px overflow-hidden rounded-[14px] bg-[#e6e8ec] [grid-template-columns:repeat(auto-fit,minmax(160px,1fr))]">
        {rows.map(([k, v]) => (
          <div key={k} className="flex flex-col gap-1 bg-white px-4 py-3.5">
            <span className="text-xs text-ink-3">{k}</span>
            <span className="tnum break-words text-[15px] font-semibold">{v}</span>
          </div>
        ))}
      </div>
      <div className="flex flex-wrap gap-2.5">
        <button type="button" className="btn-primary" onClick={onNew}>Nouveau virement</button>
        <Link to="/history" className="btn-ghost h-12">Voir l'historique</Link>
      </div>
    </div>
  )
}
