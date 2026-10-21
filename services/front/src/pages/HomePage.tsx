import { useNavigate } from 'react-router-dom'
import { Icon } from '../components/icons'
import { AccountCard, Avatar, Card, EmptyState, ErrorState, H2, LoadingState, TxRow } from '../components/ui'
import { useBankData } from '../hooks/useBankData'
import { useSpending } from '../hooks/useSpending'
import { useShell } from '../hooks/shell-context'
import { useTxViews } from '../hooks/useTxViews'
import { recipients, spendingPeriod } from '../lib/bank'
import { categoryLabel, formatShare } from '../lib/categories'
import { formatMoney } from '../lib/format'
import type { SendRouteState } from './SendPage'

export function HomePage() {
  const { accounts, beneficiaries } = useBankData()
  const { views } = useTxViews()
  const { toast } = useShell()
  const navigate = useNavigate()
  const spending = useSpending('month')
  // Part de la 1re catégorie du mois (maquette « Alimentation 73 % ») ; rien si vide ou en erreur.
  const topCategory = spending.data?.byCategory[0]

  if (accounts.error && !accounts.data) return <ErrorState error={accounts.error} onRetry={accounts.reload} />
  if (!accounts.data) return <LoadingState label="Chargement des comptes…" />
  if (accounts.data.length === 0) return <EmptyState title="Aucun compte" text="Ajoutez un compte pour voir vos soldes et vos opérations." />

  const list = accounts.data
  const total = list.reduce((s, a) => s + a.balance, 0)
  // Le compte débité par défaut (1er) n'est pas un destinataire possible.
  const people = recipients(list, views ?? [], list[0]!.id, beneficiaries.data ?? []).slice(0, 6)
  const month = spendingPeriod(views ?? [], 'month', 0)
  const addAccount = () => toast('Ouverture de compte indisponible dans la démonstration')
  const sendTo = (to?: string) => navigate('/send', { state: { to } satisfies SendRouteState })

  return (
    <div className="flex flex-col gap-[22px]">
      <section aria-labelledby="h-acc" className="flex flex-col gap-2.5">
        <div className="flex items-center justify-between">
          <H2 id="h-acc">Vos comptes</H2>
          <button type="button" onClick={addAccount} className="flex min-h-11 items-center gap-2 border-0 bg-transparent px-1 text-sm font-medium text-ink-2">
            <span className="grid h-7 w-7 place-items-center rounded-[9px] bg-night text-white">
              <Icon name="plus" size={16} />
            </span>
            Ajouter
          </button>
        </div>
        <div className="flex snap-x snap-mandatory gap-3.5 overflow-x-auto px-0.5 pt-0.5 pb-4">
          {list.map((a, i) => (
            <AccountCard key={a.id} account={a} index={i} onClick={() => navigate('/rib', { state: { account: a.id } })} />
          ))}
          <button
            type="button"
            onClick={addAccount}
            className="flex h-[156px] w-[120px] flex-none flex-col items-center justify-center gap-2.5 rounded-3xl border-[1.5px] border-dashed border-[#c4c7cc] bg-transparent text-sm font-medium text-ink-2"
          >
            <span className="grid h-10 w-10 place-items-center rounded-[14px] bg-white text-ink">
              <Icon name="plus" />
            </span>
            Ajouter
          </button>
        </div>
      </section>

      <Card className="gap-1.5 rounded-3xl p-5">
        <span className="text-sm font-medium text-ink-3">Solde total</span>
        <span data-testid="balance" className="tnum text-[32px] font-bold tracking-[-0.03em]">
          {formatMoney(total, list[0]!.currency)}
        </span>
        <span className="text-[13px] text-ink-3">
          Sur {list.length} compte{list.length > 1 ? 's' : ''} · au {new Date().toLocaleDateString('fr-FR', { day: 'numeric', month: 'long', year: 'numeric' })}
        </span>
      </Card>

      <div className="grid items-stretch gap-[22px] [grid-template-columns:repeat(auto-fit,minmax(min(100%,380px),1fr))]">
        <div className="flex min-w-0 flex-col gap-[22px]">
          <section aria-labelledby="h-to" className="flex flex-col gap-3">
            <H2 id="h-to">Envoyer à</H2>
            <div className="flex gap-3 overflow-x-auto px-0.5 pt-0.5 pb-1.5">
              <button type="button" aria-label="Nouveau virement" onClick={() => sendTo()} className="round-btn h-14 w-14">
                <Icon name="plus" />
              </button>
              {people.map((p, i) => (
                <button key={p.id} type="button" aria-label={`Envoyer à ${p.name}`} onClick={() => sendTo(p.id)} className="flex w-[60px] flex-none flex-col items-center gap-1.5 border-0 bg-transparent p-0">
                  <Avatar text={p.badge} index={i} />
                  <span className="max-w-[60px] truncate text-xs text-ink-2">{p.short}</span>
                </button>
              ))}
            </div>
          </section>

          <Card aria-labelledby="h-sp" className="flex-1 gap-3.5 p-[18px]">
            <H2 id="h-sp">Dépenses</H2>
            <div className="grid grid-cols-3 gap-2.5">
              <button
                type="button"
                onClick={() => navigate('/stats')}
                className="col-span-2 flex min-h-[108px] items-center gap-3.5 rounded-[22px] border-0 bg-[linear-gradient(140deg,#8b6bff_0%,#5b34e0_70%)] p-4 text-left text-white shadow-[0_16px_28px_-16px_rgba(91,52,224,.7)]"
              >
                <span className="grid h-[62px] w-[62px] flex-none place-items-center rounded-full bg-white/25">
                  <Icon name="chart" size={28} />
                </span>
                <span className="flex min-w-0 flex-col gap-0.5">
                  <span className="tnum text-[26px] font-bold tracking-[-0.02em]">{formatMoney(month.total)}</span>
                  <span className="text-[13px] text-[#efeaff]">dépensés en {month.label.toLowerCase()}</span>
                  {topCategory && (
                    <span data-testid="top-category" className="text-[13px] font-semibold text-white">
                      {categoryLabel(topCategory.category)} {formatShare(topCategory.share)}
                    </span>
                  )}
                </span>
              </button>
              <button type="button" onClick={() => navigate('/stats')} className="flex min-h-[108px] flex-col items-center justify-center gap-2 rounded-[22px] border-0 bg-page p-3">
                <span className="grid h-11 w-11 place-items-center rounded-[14px] bg-white">
                  <Icon name="chart" />
                </span>
                <span className="text-[13px] font-semibold">Statistiques</span>
              </button>
            </div>
          </Card>
        </div>

        <RecentOps />
      </div>
    </div>
  )
}

function RecentOps() {
  const { transactions } = useBankData()
  const { views } = useTxViews()
  const navigate = useNavigate()
  return (
    <Card aria-labelledby="h-rec" className="min-w-0 gap-1 px-3 pt-[18px] pb-2.5">
      <div className="flex items-center justify-between px-2">
        <H2 id="h-rec">Opérations récentes</H2>
        <button type="button" onClick={() => navigate('/history')} className="min-h-11 border-0 bg-transparent px-1 text-sm font-semibold text-ink-2 underline underline-offset-[3px]">
          Voir tout
        </button>
      </div>
      {transactions.error && !views ? (
        <div role="alert" className="flex flex-col items-start gap-2 px-2 py-4 text-sm text-ink-3">
          Impossible de charger les opérations.
          <button type="button" onClick={transactions.reload} className="btn-ghost h-10 text-sm">
            Réessayer
          </button>
        </div>
      ) : !views ? (
        <div role="status" aria-label="Chargement des opérations…" className="flex flex-col gap-3 p-2">
          {[1, 2, 3].map((k) => (
            <div key={k} className="h-12 animate-sk rounded-2xl bg-[#eef0f2]" />
          ))}
        </div>
      ) : views.length === 0 ? (
        <p className="m-0 px-2 py-6 text-center text-[15px] text-ink-3">Aucune opération pour le moment.</p>
      ) : (
        views.slice(0, 5).map((v) => <TxRow key={v.tx.id} view={v} onOpen={() => navigate(`/operations/${v.tx.id}`)} />)
      )}
    </Card>
  )
}
