import type { Account } from '../types/api'
import { formatMoney } from '../lib/format'

export function BalanceCard({ account }: { account: Account }) {
  return (
    <article className="rounded-xl bg-white p-6 shadow-sm ring-1 ring-slate-200" aria-label={`Compte ${account.label ?? account.id}`}>
      <p className="text-sm text-slate-500">{account.label ?? 'Compte'} · <span className="font-mono">{account.id}</span></p>
      <p className="mt-2 text-3xl font-semibold tabular-nums text-slate-900" data-testid="balance">
        {formatMoney(account.balance, account.currency)}
      </p>
    </article>
  )
}
