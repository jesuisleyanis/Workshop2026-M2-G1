import { useState, type FormEvent } from 'react'
import { api } from '../api'
import { Field } from './Field'
import { ErrorBanner } from './ErrorBanner'
import { formatMoney } from '../lib/format'
import { parseAmount, validateTransfer, type TransferErrors } from '../lib/validation'
import type { Account, Transaction } from '../types/api'

interface Props {
  accounts: Account[]
  onDone?: (tx: Transaction) => void
}

export function TransferForm({ accounts, onDone }: Props) {
  const [from, setFrom] = useState(accounts[0]?.id ?? '')
  const [to, setTo] = useState('')
  const [amount, setAmount] = useState('')
  const [label, setLabel] = useState('')
  const [errors, setErrors] = useState<TransferErrors>({})
  const [submitting, setSubmitting] = useState(false)
  const [apiError, setApiError] = useState<unknown>(null)
  const [done, setDone] = useState<Transaction | null>(null)

  const account = accounts.find((a) => a.id === from)

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    setApiError(null)
    setDone(null)
    const found = validateTransfer({ fromAccount: from, toAccount: to, amount, balance: account?.balance ?? null })
    setErrors(found)
    if (Object.keys(found).length > 0) return

    setSubmitting(true)
    try {
      const tx = await api.createTransaction({
        from_account: from,
        to_account: to.trim(),
        amount: parseAmount(amount),
        currency: account?.currency,
        label: label.trim() || undefined,
      })
      setDone(tx)
      setTo('')
      setAmount('')
      setLabel('')
      onDone?.(tx)
    } catch (err) {
      setApiError(err)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <form onSubmit={onSubmit} noValidate className="space-y-5 rounded-xl bg-white p-6 shadow-sm ring-1 ring-slate-200">
      <div className="space-y-1">
        <label htmlFor="from_account" className="block text-sm font-medium text-slate-700">Compte à débiter</label>
        <select
          id="from_account"
          value={from}
          onChange={(e) => setFrom(e.target.value)}
          className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2"
        >
          {accounts.map((a) => (
            <option key={a.id} value={a.id}>
              {a.label ?? a.id} — {formatMoney(a.balance, a.currency)}
            </option>
          ))}
        </select>
        {errors.fromAccount && <p className="text-sm text-red-700">{errors.fromAccount}</p>}
      </div>
      <Field label="Compte bénéficiaire" value={to} onChange={(e) => setTo(e.target.value)} error={errors.toAccount} autoComplete="off" />
      <Field label="Montant" inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} error={errors.amount} hint="Ex. 25,50" />
      <Field label="Libellé (optionnel)" value={label} onChange={(e) => setLabel(e.target.value)} maxLength={80} />

      {apiError !== null && <ErrorBanner error={apiError} />}
      {done && (
        <p role="status" className="rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-emerald-800">
          Virement {done.status === 'created' ? 'accepté' : 'refusé'} : {formatMoney(done.amount, done.currency)} vers {done.toAccount}.
        </p>
      )}

      <button
        type="submit"
        disabled={submitting}
        className="w-full rounded-lg bg-teal-700 px-4 py-2.5 font-medium text-white hover:bg-teal-800 disabled:cursor-not-allowed disabled:opacity-60"
      >
        {submitting ? 'Envoi…' : 'Envoyer le virement'}
      </button>
    </form>
  )
}
