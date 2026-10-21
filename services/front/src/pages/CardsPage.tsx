import { useState, type ReactNode } from 'react'
import { api } from '../api'
import { ApiError } from '../api/errors'
import { Icon } from '../components/icons'
import { Switch } from '../components/Switch'
import { Alert, ConfirmDialog, EmptyState, ErrorState, LoadingState } from '../components/ui'
import { useCards } from '../hooks/useCards'
import { useShell } from '../hooks/shell-context'
import { accountName } from '../lib/bank'
import { userMessage } from '../lib/errorMessages'
import { formatMoney } from '../lib/format'
import type { Card, CardPatch } from '../types/api'

/** Bornes du plafond de paiement (miroir des bornes serveur, qui restent l'autorité). */
export const CARD_LIMIT_MAX = 10_000
export const CARD_LIMIT_STEP = 50

const cardError = (e: unknown) =>
  e instanceof ApiError && e.code === 'card_frozen'
    ? 'Carte gelée : dégelez-la avant de modifier ses réglages.'
    : e instanceof ApiError && e.code === 'validation_error'
      ? 'Réglage refusé : valeur hors des bornes autorisées.'
      : e instanceof ApiError && e.code === 'card_not_found'
        ? 'Cette carte n’existe plus ou n’est pas accessible.'
        : userMessage(e)

const expiry = (c: Card) => `${String(c.expiryMonth).padStart(2, '0')}/${String(c.expiryYear % 100).padStart(2, '0')}`

/** D11 — Cartes : visuel, gel / dégel confirmé, plafond de paiement, sans contact, paiement en ligne (#47). */
export function CardsPage() {
  const cards = useCards()
  const [replaced, setReplaced] = useState<Record<string, Card>>({})

  if (cards.error && !cards.data) return <ErrorState error={cards.error} onRetry={cards.reload} />
  if (!cards.data) return <LoadingState label="Chargement des cartes…" />
  if (cards.data.length === 0) return <EmptyState title="Aucune carte" text="Aucune carte n’est associée à vos comptes." icon="card" />

  return (
    <div className="mx-auto flex w-full max-w-[620px] flex-col gap-6">
      {cards.data.map((c) => {
        const card = replaced[c.id] ?? c
        return <CardPanel key={card.id} card={card} onChange={(next) => setReplaced((m) => ({ ...m, [next.id]: next }))} />
      })}
    </div>
  )
}

function CardPanel({ card, onChange }: { card: Card; onChange: (c: Card) => void }) {
  const { toast } = useShell()
  const [confirm, setConfirm] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [limit, setLimit] = useState(card.paymentLimit)
  const frozen = card.status === 'frozen'

  const run = async (action: () => Promise<Card>, done?: string) => {
    setBusy(true)
    setErr(null)
    try {
      const next = await action()
      onChange(next)
      setLimit(next.paymentLimit)
      if (done) toast(done)
    } catch (e) {
      setErr(cardError(e))
    } finally {
      setBusy(false)
    }
  }
  const toggleFreeze = () => {
    setConfirm(false)
    void run(() => (frozen ? api.unfreezeCard(card.id) : api.freezeCard(card.id)), frozen ? 'Carte dégelée' : 'Carte gelée')
  }
  const update = (patch: CardPatch, done: string) => void run(() => api.updateCard(card.id, patch), done)

  return (
    <section aria-label={`Carte •••• ${card.last4}`} className="flex flex-col gap-4">
      <div
        data-testid="card-visual"
        className={`relative flex h-[200px] flex-col justify-between rounded-[26px] p-6 text-white shadow-[0_24px_40px_-24px_rgba(18,19,22,.8)] ${frozen ? 'bg-[#5d6068] opacity-70 grayscale' : 'bg-night'}`}
      >
        <div className="flex items-start justify-between">
          <span className="text-sm font-medium text-ink-4">{accountName(card.accountId)}</span>
          {frozen ? (
            <span className="flex items-center gap-1.5 rounded-full bg-white px-3 py-1 text-[13px] font-bold text-ink">
              <Icon name="lock" size={14} />
              Gelée
            </span>
          ) : (
            <span className="rounded-full bg-white/15 px-3 py-1 text-[13px] font-semibold">Active</span>
          )}
        </div>
        <span className="font-mono text-[22px] tracking-[0.12em]">•••• •••• •••• {card.last4}</span>
        <div className="flex items-end justify-between text-[13px]">
          <span className="flex flex-col">
            <span className="text-ink-4">Titulaire</span>
            <span className="font-semibold tracking-[0.04em]">{card.holder}</span>
          </span>
          <span className="flex flex-col text-right">
            <span className="text-ink-4">Expire</span>
            <span className="tnum font-semibold">{expiry(card)}</span>
          </span>
        </div>
      </div>

      <button type="button" disabled={busy} onClick={() => setConfirm(true)} className={frozen ? 'btn-primary' : 'btn-ghost'}>
        <Icon name="lock" size={18} />
        {frozen ? 'Dégeler la carte' : 'Geler la carte'}
      </button>

      {err && <Alert>{err}</Alert>}

      <section aria-label="Réglages de la carte" className="card flex flex-col gap-1 p-[18px]">
        {frozen && <p className="m-0 pb-2 text-sm text-ink-3">Carte gelée : réglages verrouillés jusqu’au dégel.</p>}
        <div className="flex flex-col gap-2.5 py-2">
          <label htmlFor={`limit-${card.id}`} className="flex justify-between text-[15px] font-semibold">
            Plafond de paiement
            <span className="tnum">{formatMoney(limit)}</span>
          </label>
          <input
            id={`limit-${card.id}`}
            type="range"
            min={0}
            max={CARD_LIMIT_MAX}
            step={CARD_LIMIT_STEP}
            value={limit}
            disabled={frozen || busy}
            onChange={(e) => setLimit(Number(e.target.value))}
            className="w-full accent-[#121316]"
          />
          <button
            type="button"
            disabled={frozen || busy || limit === card.paymentLimit}
            onClick={() => update({ paymentLimit: limit }, 'Plafond de paiement enregistré')}
            className="btn-primary min-h-11 self-end px-4 text-sm"
          >
            Enregistrer
          </button>
        </div>
        <Row label="Sans contact">
          <Switch label="Sans contact" checked={card.contactless} disabled={frozen || busy} onChange={(v) => update({ contactless: v }, v ? 'Sans contact activé' : 'Sans contact désactivé')} />
        </Row>
        <Row label="Paiement en ligne">
          <Switch label="Paiement en ligne" checked={card.onlinePayments} disabled={frozen || busy} onChange={(v) => update({ onlinePayments: v }, v ? 'Paiement en ligne activé' : 'Paiement en ligne désactivé')} />
        </Row>
      </section>

      {confirm && (
        <ConfirmDialog
          title={frozen ? 'Dégeler la carte ?' : 'Geler la carte ?'}
          text={frozen ? 'La carte pourra de nouveau être utilisée pour payer.' : 'Tous les paiements avec cette carte seront refusés jusqu’au dégel. Vous pourrez la dégeler à tout moment.'}
          confirmLabel={frozen ? 'Dégeler' : 'Geler'}
          icon="lock"
          danger={!frozen}
          onConfirm={toggleFreeze}
          onCancel={() => setConfirm(false)}
        />
      )}
    </section>
  )
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex min-h-[56px] items-center justify-between gap-4 border-t border-mute py-2">
      <span className="text-[15px] font-semibold">{label}</span>
      {children}
    </div>
  )
}
