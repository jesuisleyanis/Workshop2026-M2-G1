import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Empty, ErrorBlock, Loading } from '../components/ui'
import { useBankData } from '../hooks/useBankData'
import { formatIban, formatMoney } from '../lib/format'
import type { TransferRouteState } from './TransferPage'

export function AccountsPage() {
  const { accounts } = useBankData()
  const navigate = useNavigate()
  const [copied, setCopied] = useState<string | null>(null)

  useEffect(() => {
    if (copied === null) return
    const id = setTimeout(() => setCopied(null), 1600)
    return () => clearTimeout(id)
  }, [copied])

  if (accounts.loading && !accounts.data) return <Loading label="Chargement des comptes…" count={2} className="h-28 rounded-[18px]" />
  if (accounts.error) return <ErrorBlock title="Impossible de charger vos comptes" error={accounts.error} onRetry={accounts.reload} />
  if (!accounts.data?.length) return <Empty>Aucun compte n'est rattaché à cet utilisateur.</Empty>

  return (
    <section aria-label="Liste des comptes" className="flex flex-col gap-3.5">
      {accounts.data.map((a) => {
        const state: TransferRouteState = { fromAccount: a.id }
        return (
          <article
            key={a.id}
            aria-label={`Compte #${a.id}`}
            className="grid items-center gap-4 rounded-[20px] border-[1.5px] border-[#eceef1] p-5 [grid-template-columns:repeat(auto-fit,minmax(min(100%,220px),1fr))]"
          >
            <div className="flex min-w-0 flex-col gap-1.5">
              <div className="flex items-center gap-2">
                <span className="text-base font-semibold">Compte #{a.id}</span>
                <span className="rounded-md bg-[#eceef1] px-2 py-0.5 text-[11px] text-ink-2">{a.currency}</span>
              </div>
              {a.iban && <span className="break-words font-mono text-[13px] text-ink-2">{formatIban(a.iban)}</span>}
            </div>
            <div className="flex flex-col gap-0.5">
              <span className="text-xs text-ink-3">Solde</span>
              <span className="tnum text-[26px] font-semibold tracking-[-0.03em]">{formatMoney(a.balance, a.currency)}</span>
            </div>
            <div className="flex flex-wrap justify-end gap-2">
              {a.iban && (
                <button
                  type="button"
                  className="btn-ghost"
                  onClick={() => {
                    void navigator.clipboard?.writeText(a.iban!)
                    setCopied(a.id)
                  }}
                >
                  {copied === a.id ? 'IBAN copié' : "Copier l'IBAN"}
                </button>
              )}
              <button type="button" className="btn-primary h-11 text-sm" onClick={() => navigate('/transfer', { state })}>
                Virer depuis ce compte
              </button>
            </div>
          </article>
        )
      })}
    </section>
  )
}
