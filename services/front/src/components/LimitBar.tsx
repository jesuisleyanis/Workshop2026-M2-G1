import { formatMoney } from '../lib/format'
import { remainingShare, resetLabel } from '../lib/limits'
import type { AccountLimit } from '../types/api'

/** D10 : « Plafond restant » (restant / plafond, % restant, remise à zéro). Sobre si sans plafond (#46). */
export function LimitBar({ limit, currency = 'EUR', label = 'Plafond restant' }: { limit: AccountLimit; currency?: string; label?: string }) {
  const share = remainingShare(limit)
  if (share === null || limit.limit === null || limit.remaining === null) {
    return (
      <div data-testid="limit-bar" className="flex items-center justify-between gap-3">
        <span className="text-sm font-medium text-ink-3">{label}</span>
        <span className="text-sm font-semibold text-ink-2">Sans plafond</span>
      </div>
    )
  }
  const pct = Math.round(share * 100)
  return (
    <div data-testid="limit-bar" className="flex flex-col gap-2">
      <div className="flex items-baseline justify-between gap-3">
        <span className="text-sm font-medium text-ink-3">{label}</span>
        <span className="tnum text-sm font-semibold">{pct} %</span>
      </div>
      <div
        role="meter"
        aria-label={label}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={pct}
        aria-valuetext={`${formatMoney(limit.remaining, currency)} restants sur ${formatMoney(limit.limit, currency)}`}
        className="h-2.5 overflow-hidden rounded-full bg-mute"
      >
        <div className={`h-full rounded-full ${pct <= 10 ? 'bg-ko-fg' : 'bg-night'}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-[13px] text-ink-3">
        <span className="tnum font-semibold text-ink">{formatMoney(limit.remaining, currency)}</span> sur {formatMoney(limit.limit, currency)} · remise à zéro le {resetLabel(limit.periodEnd)}
      </span>
    </div>
  )
}
