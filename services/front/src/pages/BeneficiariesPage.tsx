import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api'
import { ApiError } from '../api/errors'
import { Icon } from '../components/icons'
import { Alert, Avatar, ConfirmDialog, EmptyState, ErrorState, LoadingState } from '../components/ui'
import { useBankData } from '../hooks/useBankData'
import { useShell } from '../hooks/shell-context'
import { initials } from '../lib/bank'
import { userMessage } from '../lib/errorMessages'
import { formatIban } from '../lib/format'
import type { Beneficiary } from '../types/api'
import type { SendRouteState } from './SendPage'

/** Refus métier de POST /api/v1/beneficiaries, formulés pour le client. */
const ADD_ERRORS: Record<string, string> = {
  account_not_found: 'Aucun compte ne correspond à cet IBAN.',
  beneficiary_exists: 'Ce bénéficiaire est déjà enregistré.',
  own_account: 'C’est l’un de vos comptes : inutile de l’enregistrer.',
  beneficiary_limit: 'Nombre maximal de bénéficiaires atteint.',
}

const addError = (e: unknown) => (e instanceof ApiError && ADD_ERRORS[e.code]) || userMessage(e)

/** D7 — Bénéficiaires : liste, recherche, ajout (nom + IBAN), suppression confirmée, « Envoyer ». */
export function BeneficiariesPage() {
  const { beneficiaries } = useBankData()
  const { toast } = useShell()
  const navigate = useNavigate()
  const [q, setQ] = useState('')
  const [adding, setAdding] = useState(false)
  const [removing, setRemoving] = useState<Beneficiary | null>(null)

  if (beneficiaries.error && !beneficiaries.data) return <ErrorState error={beneficiaries.error} onRetry={beneficiaries.reload} />
  if (!beneficiaries.data) return <LoadingState label="Chargement des bénéficiaires…" />

  const query = q.trim().toLowerCase()
  const compact = query.replace(/\s+/g, '')
  const shown = beneficiaries.data.filter(
    (b) => !query || b.name.toLowerCase().includes(query) || (compact !== '' && b.iban.replace(/\s+/g, '').toLowerCase().includes(compact)),
  )
  const sendTo = (b: Beneficiary) => navigate('/send', { state: { to: b.accountId } satisfies SendRouteState })
  const remove = async (b: Beneficiary) => {
    setRemoving(null)
    try {
      await api.deleteBeneficiary(b.id)
      toast(`${b.name} supprimé`)
    } catch (e) {
      toast(userMessage(e))
    }
    beneficiaries.reload()
  }

  return (
    <div className="mx-auto flex w-full max-w-[620px] flex-col gap-4">
      <div className="flex items-center gap-3">
        <label className="relative flex flex-1 items-center">
          <span className="absolute left-4 text-ink-3">
            <Icon name="search" />
          </span>
          <input type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Nom ou IBAN" aria-label="Rechercher un bénéficiaire" className="search bg-white" />
        </label>
        <button type="button" onClick={() => setAdding((v) => !v)} aria-expanded={adding} className="btn-primary min-h-12 flex-none px-4">
          <Icon name={adding ? 'x' : 'plus'} size={18} />
          {adding ? 'Fermer' : 'Ajouter'}
        </button>
      </div>

      {adding && (
        <AddForm
          onAdded={(b) => {
            setAdding(false)
            toast(`${b.name} ajouté`)
            beneficiaries.reload()
          }}
        />
      )}

      {beneficiaries.data.length === 0 ? (
        <EmptyState title="Aucun bénéficiaire" text="Ajoutez un bénéficiaire pour lui envoyer de l’argent sans ressaisir son IBAN." icon="user" />
      ) : shown.length === 0 ? (
        <EmptyState title="Aucun résultat" text={`Aucun bénéficiaire ne correspond à « ${q.trim()} ».`} icon="search" />
      ) : (
        <ul aria-label="Bénéficiaires" className="m-0 flex list-none flex-col rounded-3xl bg-white p-1.5 shadow-card">
          {shown.map((b, i) => (
            <li key={b.id} className="flex min-h-[64px] items-center gap-3 rounded-2xl px-2.5 py-2">
              <Avatar text={initials(b.name) || '?'} index={i} size={44} />
              <span className="flex min-w-0 flex-1 flex-col">
                <span className="truncate text-[15px] font-semibold">{b.name}</span>
                <span className="truncate font-mono text-[13px] text-ink-3">{formatIban(b.iban)}</span>
              </span>
              <button type="button" onClick={() => sendTo(b)} aria-label={`Envoyer à ${b.name}`} className="round-btn h-11 w-11">
                <Icon name="send" size={18} />
              </button>
              <button type="button" onClick={() => setRemoving(b)} aria-label={`Supprimer ${b.name}`} className="round-btn h-11 w-11 text-ko-fg">
                <Icon name="x" size={18} />
              </button>
            </li>
          ))}
        </ul>
      )}

      {removing && (
        <ConfirmDialog
          title={`Supprimer ${removing.name} ?`}
          text="Le bénéficiaire disparaîtra de vos destinataires. Vos opérations passées sont conservées."
          confirmLabel="Supprimer"
          icon="x"
          danger
          onConfirm={() => void remove(removing)}
          onCancel={() => setRemoving(null)}
        />
      )}
    </div>
  )
}

function AddForm({ onAdded }: { onAdded: (b: Beneficiary) => void }) {
  const [name, setName] = useState('')
  const [iban, setIban] = useState('')
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    if (!name.trim() || iban.replace(/\s+/g, '').length < 4) {
      setErr('Saisissez un nom et un IBAN.')
      return
    }
    setBusy(true)
    setErr(null)
    try {
      onAdded(await api.addBeneficiary({ name: name.trim(), iban }))
    } catch (e2) {
      setErr(addError(e2))
    } finally {
      setBusy(false)
    }
  }

  return (
    <form onSubmit={(e) => void submit(e)} aria-label="Nouveau bénéficiaire" className="card flex flex-col gap-3.5 p-[18px]" noValidate>
      <label className="flex flex-col gap-1.5 text-sm font-medium text-ink-2">
        Nom
        <input value={name} onChange={(e) => setName(e.target.value.slice(0, 64))} placeholder="Ex. Léa Martin" autoComplete="off" className="field" />
      </label>
      <label className="flex flex-col gap-1.5 text-sm font-medium text-ink-2">
        IBAN
        <input value={iban} onChange={(e) => setIban(e.target.value.slice(0, 42))} placeholder="FR76 0000 0000 …" autoComplete="off" spellCheck={false} className="field font-mono" />
      </label>
      {err && <Alert>{err}</Alert>}
      <button type="submit" disabled={busy} className="btn-primary">
        {busy ? 'Enregistrement…' : 'Enregistrer le bénéficiaire'}
      </button>
    </form>
  )
}
