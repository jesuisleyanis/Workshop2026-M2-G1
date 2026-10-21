import { useState, type ReactNode } from 'react'
import { useLocation } from 'react-router-dom'
import { Icon } from '../components/icons'
import { EmptyState, ErrorState, LoadingState } from '../components/ui'
import { useShell } from '../hooks/shell-context'
import { copyText } from '../lib/clipboard'
import { useAuth } from '../hooks/useAuth'
import { useBankData } from '../hooks/useBankData'
import { accountName } from '../lib/bank'
import { formatIban } from '../lib/format'

/** Coordonnées fictives de la banque de démonstration. */
const BIC = 'BRESFRPPXXX'
const BANK = 'Banque Résilience — Agence Démo'
const ADDRESS = '12 rue de l’Exemple, 75000 Paris'

export function RibPage() {
  const { accounts } = useBankData()
  const { username } = useAuth()
  const { toast } = useShell()
  const initial = (useLocation().state as { account?: string } | null)?.account
  const [picked, setPicked] = useState<string | null>(initial ?? null)

  if (accounts.error && !accounts.data) return <ErrorState error={accounts.error} onRetry={accounts.reload} />
  if (!accounts.data) return <LoadingState label="Chargement des comptes…" />
  if (accounts.data.length === 0) return <EmptyState title="Aucun compte" text="Aucun RIB disponible pour le moment." icon="bank" />

  const acc = accounts.data.find((a) => a.id === picked) ?? accounts.data[0]!
  const iban = acc.iban ? formatIban(acc.iban) : `Compte n°${acc.id}`
  const holder = username ?? 'Client'
  const copy = (text: string, msg: string) => void copyText(text).then((ok) => toast(ok ? msg : 'Copie impossible : sélectionnez le texte'))
  const share = () => {
    const text = `RIB ${accountName(acc.id)} — ${holder} — IBAN ${iban} — BIC ${BIC}`
    if (navigator.share) void navigator.share({ title: 'RIB Banque Résilience', text }).catch(() => {})
    else copy(text, 'RIB copié pour le partage')
  }

  return (
    <div className="mx-auto flex w-full max-w-[620px] flex-col gap-4">
      <div role="group" aria-label="Compte" className="flex gap-2 overflow-x-auto pb-1">
        {accounts.data.map((a) => (
          <button
            key={a.id}
            type="button"
            aria-pressed={a.id === acc.id}
            onClick={() => setPicked(a.id)}
            className={`min-h-11 flex-none rounded-full border-[1.5px] px-4 text-sm font-semibold whitespace-nowrap ${a.id === acc.id ? 'border-ink bg-night text-white' : 'border-line bg-white text-ink'}`}
          >
            {accountName(a.id)}
          </button>
        ))}
      </div>
      <section data-print aria-label={`RIB du ${accountName(acc.id)}`} className="card flex flex-col gap-1 p-6">
        <span className="text-sm font-medium text-ink-3">{accountName(acc.id)}</span>
        <dl className="m-0 mt-2 flex flex-col">
          <Row k="Titulaire">
            <span className="text-base font-semibold">{holder}</span>
          </Row>
          <Row k="IBAN">
            <span className="font-mono text-[17px] font-medium tracking-[0.02em] break-words">{iban}</span>
          </Row>
          <Row k="BIC">
            <span className="font-mono text-base">{BIC}</span>
          </Row>
          <Row k="Domiciliation">
            <span className="text-[15px] leading-snug">
              {BANK}
              <br />
              {ADDRESS}
            </span>
          </Row>
        </dl>
      </section>
      <div className="grid grid-cols-3 gap-2.5">
        <button type="button" onClick={() => copy(iban, 'IBAN copié')} className="flex min-h-[72px] flex-col items-center justify-center gap-1.5 rounded-[20px] border-0 bg-night text-sm font-semibold text-white">
          <Icon name="copy" />
          Copier
        </button>
        <button type="button" onClick={share} className="flex min-h-[72px] flex-col items-center justify-center gap-1.5 rounded-[20px] border-[1.5px] border-line bg-white text-sm font-semibold">
          <Icon name="share" />
          Partager
        </button>
        <button type="button" onClick={() => window.print()} className="flex min-h-[72px] flex-col items-center justify-center gap-1.5 rounded-[20px] border-[1.5px] border-line bg-white text-sm font-semibold">
          <Icon name="print" />
          Imprimer
        </button>
      </div>
      <p className="m-0 text-center text-[13px] text-ink-3">Coordonnées fictives — démonstrateur pédagogique.</p>
    </div>
  )
}

function Row({ k, children }: { k: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-1 border-t border-mute py-3">
      <dt className="text-[13px] text-ink-3">{k}</dt>
      <dd className="m-0">{children}</dd>
    </div>
  )
}
