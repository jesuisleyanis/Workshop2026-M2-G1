import { formatTime } from '../lib/format'
import type { VerifyTx } from '../types/events'
import { Panel } from './Panel'

export function VerificationCard({ verify }: { verify: VerifyTx | null }) {
  return (
    <Panel title="Dernière transaction de vérification">
      {verify ? (
        <div data-testid="verification" data-ok={verify.ok}>
          <p className={`text-5xl font-black ${verify.ok ? 'text-emerald-300' : 'text-red-300'}`}>{verify.ok ? '✓ SUCCÈS' : '✕ ÉCHEC'}</p>
          <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-base text-slate-300">
            <dt className="text-slate-500">Heure</dt>
            <dd className="font-mono">{formatTime(verify.ts)}</dd>
            <dt className="text-slate-500">Transaction</dt>
            <dd className="truncate font-mono">{verify.txId ?? '--'}</dd>
            <dt className="text-slate-500">Durée</dt>
            <dd className="font-mono">{verify.durationMs !== null ? `${Math.round(verify.durationMs)} ms` : '--'}</dd>
          </dl>
        </div>
      ) : (
        <p className="py-4 text-xl text-slate-500" data-testid="verification">Aucune vérification reçue.</p>
      )}
    </Panel>
  )
}
