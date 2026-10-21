import { LimitBar } from '../components/LimitBar'
import { EmptyState, ErrorState, LoadingState } from '../components/ui'
import { useBankData } from '../hooks/useBankData'
import { accountName } from '../lib/bank'
import { formatMoney } from '../lib/format'
import { resetLabel } from '../lib/limits'

/** D10 — Plafonds : par compte, plafond mensuel, consommé, restant, remise à zéro (#46). Le serveur reste l'autorité. */
export function LimitsPage() {
  const { accounts, limits } = useBankData()

  if (limits.error && !limits.data) return <ErrorState error={limits.error} onRetry={limits.reload} />
  if (!limits.data) return <LoadingState label="Chargement des plafonds…" />
  if (limits.data.length === 0) return <EmptyState title="Aucun compte" text="Aucun plafond à afficher pour le moment." icon="sliders" />

  const currency = (id: string) => accounts.data?.find((a) => a.id === id)?.currency ?? 'EUR'
  return (
    <div className="mx-auto flex w-full max-w-[620px] flex-col gap-4">
      {limits.data.map((l) => {
        const cur = currency(l.accountId)
        return (
          <section key={l.accountId} aria-label={`Plafond du ${accountName(l.accountId)}`} className="card flex flex-col gap-3.5 p-[18px]">
            <span className="text-[15px] font-semibold">{accountName(l.accountId)}</span>
            {l.limit === null ? (
              <p className="m-0 text-sm text-ink-3">Sans plafond (compte de service). Consommé ce mois-ci : {formatMoney(l.used, cur)}.</p>
            ) : (
              <>
                <LimitBar limit={l} currency={cur} />
                <dl className="m-0 flex flex-col">
                  {(
                    [
                      ['Plafond mensuel', formatMoney(l.limit, cur)],
                      ['Consommé', formatMoney(l.used, cur)],
                      ['Restant', formatMoney(l.remaining ?? 0, cur)],
                      ['Remise à zéro', `le ${resetLabel(l.periodEnd)}`],
                    ] as [string, string][]
                  ).map(([k, v]) => (
                    <div key={k} className="flex justify-between gap-4 border-t border-mute py-3">
                      <dt className="text-sm text-ink-3">{k}</dt>
                      <dd className="tnum m-0 text-right text-[15px] font-semibold">{v}</dd>
                    </div>
                  ))}
                </dl>
              </>
            )}
          </section>
        )
      })}
    </div>
  )
}
