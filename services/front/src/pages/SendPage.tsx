import { useCallback, useEffect, useMemo, useRef, useState, type PointerEvent as RPointerEvent, type ReactNode } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { api } from '../api'
import { ApiError } from '../api/errors'
import { Icon } from '../components/icons'
import { AccountCard, Alert, Avatar, Card, EmptyState, ErrorState, H2, LoadingState } from '../components/ui'
import { useBackOverride, useShell } from '../hooks/shell-context'
import { useBankData } from '../hooks/useBankData'
import { useTxViews } from '../hooks/useTxViews'
import { accountBadge, accountName, last4, recipients, type Recipient } from '../lib/bank'
import { copyText } from '../lib/clipboard'
import { userMessage } from '../lib/errorMessages'
import { formatMoney } from '../lib/format'
import { parseAmount, validateTransfer } from '../lib/validation'
import type { Account, Transaction } from '../types/api'

/** Pré-remplissage : destinataire (accueil, « Envoyer à ») et/ou compte à débiter. */
export interface SendRouteState {
  to?: string
  from?: string
}

type Step = 'form' | 'recap' | 'sending' | 'result'
type Outcome =
  | { kind: 'success'; tx: Transaction }
  | { kind: 'balance' | 'limit' | 'refused' | 'error'; error: unknown }

const QUICK = [50, 100, 150, 200]
const WIZARD = ['Destinataire', 'Montant', 'Détails', 'Confirmation']

export function SendPage() {
  const { accounts } = useBankData()
  if (accounts.error && !accounts.data) return <ErrorState error={accounts.error} onRetry={accounts.reload} />
  if (!accounts.data) return <LoadingState label="Chargement de vos comptes…" />
  if (accounts.data.length === 0) return <EmptyState title="Aucun compte" text="Aucun compte à débiter : impossible d’émettre un virement." />
  return <SendFlow accounts={accounts.data} />
}

function SendFlow({ accounts }: { accounts: Account[] }) {
  const { accounts: accountsRes, transactions, beneficiaries: beneficiariesRes, saveLabel } = useBankData()
  const beneficiaries = useMemo(() => beneficiariesRes.data ?? [], [beneficiariesRes.data])
  const { views } = useTxViews()
  const { isDesktop, toast } = useShell()
  const navigate = useNavigate()
  const prefill = (useLocation().state as SendRouteState | null) ?? {}

  const [accId, setAccId] = useState(() => (accounts.some((a) => a.id === prefill.from) ? prefill.from! : accounts[0]!.id))
  const [to, setTo] = useState<string | null>(prefill.to ?? null)
  const [amt, setAmt] = useState('50')
  const [label, setLabel] = useState('')
  const [q, setQ] = useState('')
  const [all, setAll] = useState(false)
  const [step, setStep] = useState<Step>('form')
  const [ms, setMs] = useState(prefill.to ? 2 : 1)
  const [dir, setDir] = useState<1 | -1>(1)
  const [err, setErr] = useState<string | null>(null)
  const [outcome, setOutcome] = useState<Outcome | null>(null)

  const src = accounts.find((a) => a.id === accId) ?? accounts[0]!
  const amount = parseAmount(amt) ?? 0
  const known = useMemo(() => recipients(accounts, views ?? [], src.id, beneficiaries), [accounts, views, src.id, beneficiaries])
  const query = q.trim().toLowerCase()
  const matches = known.filter((r) => !query || r.name.toLowerCase().includes(query) || r.id === query.replace(/^n°|^#/, ''))
  const typedId = /^\d+$/.test(query) && Number(query) > 0 ? String(Number(query)) : null
  if (typedId && typedId !== src.id && !matches.some((r) => r.id === typedId)) {
    matches.push({ id: typedId, name: accountName(typedId), mask: 'Nouveau destinataire', own: false, badge: accountBadge(typedId), short: `n°${typedId}` })
  }
  const toRec: Recipient | null = to ? (known.find((r) => r.id === to) ?? { id: to, name: accountName(to), mask: `Compte n°${to}`, own: false, badge: accountBadge(to), short: `n°${to}` }) : null
  const toIndex = Math.max(0, known.findIndex((r) => r.id === to))

  const goStep = useCallback(
    (n: number) => {
      setDir(n >= ms ? 1 : -1)
      setMs(n)
      setErr(null)
      setStep('form')
    },
    [ms],
  )

  // Bouton Retour de l'en-tête : étape précédente de l'assistant (mobile) ou retour au formulaire (desktop).
  const back = useMemo(() => {
    if (step === 'sending' || step === 'result') return null
    if (!isDesktop && ms > 1) return () => goStep(ms - 1)
    if (isDesktop && step === 'recap') return () => setStep('form')
    return null
  }, [step, isDesktop, ms, goStep])
  useBackOverride(back)

  function check(fields: ('to' | 'amount')[]): boolean {
    const errors = validateTransfer({ fromAccount: src.id, toAccount: to ?? '', amount: amt, balance: src.balance })
    if (fields.includes('amount') && errors.amount) return fail(errors.amount)
    if (fields.includes('to') && !to) return fail('Choisissez un destinataire.')
    if (fields.includes('to') && errors.toAccount) return fail(errors.toAccount)
    setErr(null)
    return true
  }
  function fail(message: string): false {
    setErr(message)
    return false
  }

  const pick = (id: string) => {
    setTo(id)
    setQ('')
    setErr(null)
  }

  async function execute() {
    if (!to) return
    setStep('sending')
    try {
      const tx = await api.createTransaction({ from_account: src.id, to_account: to, amount })
      if (label.trim()) saveLabel(tx.id, label.trim())
      setOutcome(tx.status === 'rejected' ? { kind: 'refused', error: null } : { kind: 'success', tx })
    } catch (e) {
      if (e instanceof ApiError && e.isUnauthorized) return // AuthProvider renvoie au login
      const kind =
        e instanceof ApiError && e.code === 'insufficient_funds'
          ? 'balance'
          : e instanceof ApiError && e.code === 'limit_exceeded'
            ? 'limit'
            : e instanceof ApiError && e.status >= 400 && e.status < 500
              ? 'refused'
              : 'error'
      setOutcome({ kind, error: e })
    }
    setStep('result')
    accountsRes.reload()
    transactions.reload()
  }

  function reset() {
    setTo(null)
    setAmt('50')
    setLabel('')
    setOutcome(null)
    goStep(1)
  }

  const cta = `Envoyer ${formatMoney(amount, src.currency)}`
  const avail = `Disponible : ${formatMoney(src.balance, src.currency)}`
  const recapRows: [string, string][] = [
    ['Depuis', `${accountName(src.id)} •••• ${last4(src.iban, src.id)}`],
    ['Vers', toRec ? `${toRec.name}${toRec.own ? ' (vous)' : ''}` : '—'],
    ['Libellé', label.trim() || '—'],
    ['Exécution', 'Immédiate'],
  ]

  if (step === 'sending') {
    return (
      <div role="status" aria-live="polite" className="mx-auto mt-10 flex w-full max-w-[560px] flex-col items-center gap-[18px] rounded-[28px] bg-white px-6 py-12 text-center">
        <span className="h-14 w-14 animate-spin-fast rounded-full border-4 border-[#e6e8eb] border-t-ink" />
        <span className="text-lg font-semibold">Envoi en cours…</span>
        <span className="text-sm text-ink-3">Ne fermez pas l’application.</span>
      </div>
    )
  }

  if (step === 'result' && outcome) {
    return (
      <ResultCard
        outcome={outcome}
        amount={amount}
        src={src}
        toName={toRec?.name ?? ''}
        onCopy={(ref) => void copyText(ref).then((ok) => toast(ok ? 'Référence copiée' : 'Copie impossible : notez la référence'))}
        onView={(id) => navigate(`/operations/${id}`)}
        onNew={reset}
        onEditAmount={() => goStep(isDesktop ? 1 : 2)}
        onHome={() => navigate('/')}
        onHistory={() => navigate('/history')}
        onRetry={() => void execute()}
        onCancel={() => (isDesktop ? setStep('recap') : goStep(4))}
      />
    )
  }

  const accountCards = (size: 'md' | 'sm') =>
    accounts.map((a, i) => (
      <AccountCard
        key={a.id}
        account={a}
        index={i}
        size={size}
        selected={a.id === src.id}
        onClick={() => {
          setAccId(a.id)
          setErr(null)
          if (to === a.id) setTo(null)
        }}
      />
    ))

  const amountBox = (big: boolean) => (
    <>
      <label className="flex items-baseline justify-center gap-1.5 pt-2.5 pb-0.5">
        <input
          aria-label="Montant en euros"
          inputMode="decimal"
          value={amt}
          onChange={(e) => {
            setAmt(e.target.value.replace(/[^\d,.]/g, '').slice(0, 9))
            setErr(null)
          }}
          style={{ width: `${Math.max(2, amt.length + 0.6)}ch` }}
          className={`tnum max-w-full border-0 border-b-2 border-line bg-transparent px-0.5 text-right font-bold tracking-[-0.03em] focus:border-ink ${big ? 'text-[52px]' : 'text-[46px]'}`}
        />
        <span aria-hidden className={`font-bold ${big ? 'text-[52px]' : 'text-[46px]'}`}>
          €
        </span>
      </label>
      <div className="grid grid-cols-4 gap-2">
        {QUICK.map((v) => (
          <button
            key={v}
            type="button"
            aria-pressed={amount === v}
            onClick={() => {
              setAmt(String(v))
              setErr(null)
            }}
            className={`min-h-11 rounded-xl border-0 text-[15px] font-semibold ${amount === v ? 'bg-night text-white' : 'bg-page text-ink'}`}
          >
            {v} €
          </button>
        ))}
      </div>
    </>
  )

  const labelField = (
    <label className="flex flex-col gap-2">
      <span className="flex justify-between text-sm font-semibold">
        Libellé <span className="text-[13px] font-normal text-ink-3">{label.length} / 140 · facultatif</span>
      </span>
      <input value={label} onChange={(e) => setLabel(e.target.value.slice(0, 140))} placeholder="Ex. Remboursement dîner" className="field" />
    </label>
  )

  // ── Desktop : formulaire en une page puis récapitulatif ──
  if (isDesktop) {
    if (step === 'recap') {
      return (
        <div className="mx-auto flex w-full max-w-[560px] flex-col gap-4">
          <Card className="gap-[18px] p-6">
            <div className="flex flex-col items-center gap-1 pt-2 pb-1">
              <span className="text-sm font-medium text-ink-3">Récapitulatif</span>
              <span className="tnum text-[42px] font-bold tracking-[-0.03em]">{formatMoney(amount, src.currency)}</span>
            </div>
            <Recap rows={recapRows} />
            <div className="grid gap-2.5 [grid-template-columns:repeat(auto-fit,minmax(160px,1fr))]">
              <button type="button" onClick={() => setStep('form')} className="btn-ghost">
                Modifier
              </button>
              <button type="button" onClick={() => void execute()} className="btn-primary">
                Confirmer l’envoi
              </button>
            </div>
          </Card>
        </div>
      )
    }
    const people = all || query ? matches : matches.slice(0, 4)
    return (
      <div className="grid items-stretch gap-5 [grid-template-columns:repeat(auto-fit,minmax(min(100%,380px),1fr))]">
        <Card aria-labelledby="h-sa" className="min-w-0 gap-2.5 px-5 pt-5 pb-3">
          <H2 id="h-sa">Choisir le compte</H2>
          <div role="group" aria-label="Compte à débiter" className="flex gap-3.5 overflow-x-auto p-1 pb-3">
            {accountCards('md')}
          </div>
        </Card>

        <Card aria-labelledby="h-rcp" className="gap-3.5 p-5">
          <H2 id="h-rcp">Choisir un destinataire</H2>
          <SearchBox value={q} onChange={setQ} placeholder="Nom ou n° de compte" label="Rechercher un destinataire par nom ou numéro de compte" />
          {toRec && (
            <div className="flex items-center gap-3 rounded-2xl bg-page py-2.5 pr-2.5 pl-4">
              <span className="text-ok-fg">
                <Icon name="check" />
              </span>
              <span className="flex flex-1 flex-col">
                <span className="text-[15px] font-semibold">{toRec.name}</span>
                <span className="font-mono text-[13px] text-ink-3">{toRec.mask}</span>
              </span>
              <button type="button" onClick={() => setTo(null)} aria-label="Retirer le destinataire" className="grid h-11 w-11 place-items-center rounded-full border-0 bg-transparent">
                <Icon name="x" />
              </button>
            </div>
          )}
          {query && matches.length === 0 && <p className="m-0 px-2 py-3 text-sm text-ink-3">Aucun destinataire ne correspond. Saisissez un numéro de compte.</p>}
          <div className="flex flex-wrap gap-3">
            {people.map((r, i) => (
              <button
                key={r.id}
                type="button"
                aria-pressed={r.id === to}
                aria-label={r.name}
                onClick={() => pick(r.id)}
                className="flex w-[60px] flex-col items-center gap-1.5 border-0 bg-transparent p-0"
              >
                <span className={`rounded-full outline-offset-2 ${r.id === to ? 'outline-[3px] outline-ink outline-solid' : ''}`}>
                  <Avatar text={r.badge} index={i} size={54} />
                </span>
                <span className="max-w-[60px] truncate text-xs text-ink-2">{r.own ? 'Vous' : `n°${r.id}`}</span>
              </button>
            ))}
            {!all && !query && matches.length > 4 && (
              <button type="button" onClick={() => setAll(true)} aria-label={`Afficher les ${matches.length - 4} autres destinataires`} className="h-[54px] w-[54px] rounded-full border-0 bg-night text-[15px] font-semibold text-white">
                +{matches.length - 4}
              </button>
            )}
          </div>
        </Card>

        <Card aria-labelledby="h-amt" className="gap-3.5 p-5">
          <H2 id="h-amt">Quel montant souhaitez-vous envoyer ?</H2>
          {amountBox(false)}
          <input
            type="range"
            min={0}
            max={2000}
            step={5}
            value={Math.min(2000, Math.round(amount))}
            onChange={(e) => setAmt(e.target.value)}
            aria-label="Curseur du montant, de 0 à 2 000 €"
            className="h-11 w-full"
          />
          <span className="text-center text-[13px] text-ink-3">{avail}</span>
        </Card>

        <Card aria-label="Détails du virement" className="gap-3.5 p-5">
          {labelField}
        </Card>

        <div className="pointer-events-none sticky bottom-4 z-[5] col-span-full flex min-w-0 flex-col items-end gap-2.5">
          {err && (
            <div role="alert" className="pointer-events-auto max-w-[min(100%,420px)] rounded-[14px] bg-ko-bg px-4 py-3 text-sm font-medium text-ko-fg shadow-[0_10px_30px_-12px_rgba(18,19,22,.35)]">
              {err}
            </div>
          )}
          <button
            type="button"
            onClick={() => check(['to', 'amount']) && setStep('recap')}
            className="btn-primary pointer-events-auto h-[58px] w-[min(100%,360px)] rounded-[18px] text-[17px] shadow-[0_18px_40px_-14px_rgba(18,19,22,.55),0_2px_6px_rgba(18,19,22,.18)]"
          >
            {cta}
          </button>
        </div>
      </div>
    )
  }

  // ── Mobile : assistant en 4 étapes ──
  const anim = dir < 0 ? 'animate-wz-back' : 'animate-wz-in'
  const toChip = toRec && (
    <div className="flex items-center gap-3 rounded-[18px] bg-white py-2.5 pr-2.5 pl-3 shadow-[0_1px_2px_rgba(18,19,22,.04)]">
      <Avatar text={toRec.badge} index={toIndex} size={40} />
      <span className="flex min-w-0 flex-1 flex-col">
        <span className="text-xs text-ink-3">À</span>
        <span className="truncate text-[15px] font-semibold">{toRec.name}</span>
      </span>
      <button type="button" onClick={() => goStep(1)} className="min-h-11 rounded-xl border-0 bg-page px-3 text-sm font-semibold">
        Modifier
      </button>
    </div>
  )
  const errBox = err && <Alert>{err}</Alert>
  const next = (label: string, onClick: () => void) => (
    <button type="button" onClick={onClick} className="btn-primary h-14 w-full rounded-[18px]">
      {label} <Icon name="chev" />
    </button>
  )

  return (
    <div className="flex flex-col gap-[18px]">
      <div className="flex flex-col gap-2.5">
        <div className="flex items-baseline justify-between gap-3">
          <h2 className="m-0 text-xl font-bold tracking-[-0.02em]">{WIZARD[ms - 1]}</h2>
          <span className="tnum text-[13px] font-medium text-ink-3">Étape {ms} sur 4</span>
        </div>
        <div role="progressbar" aria-label="Progression du virement" aria-valuemin={1} aria-valuemax={4} aria-valuenow={ms} className="grid grid-cols-4 gap-1.5">
          {WIZARD.map((w, i) => (
            <span key={w} className="block h-1 overflow-hidden rounded-full bg-line">
              <span className="block h-full rounded-full bg-night transition-[width] duration-400" style={{ width: i < ms ? '100%' : '0%' }} />
            </span>
          ))}
        </div>
      </div>

      {ms === 1 && (
        <div className={`flex flex-col gap-4 ${anim}`}>
          <SearchBox value={q} onChange={setQ} placeholder="Nom ou n° de compte" label="Rechercher un destinataire par nom ou numéro de compte" />
          <section aria-label="Destinataires" className="flex flex-col rounded-3xl bg-white p-1.5 shadow-card">
            {matches.map((r, i) => {
              const on = r.id === to
              return (
                <button
                  key={r.id}
                  type="button"
                  aria-pressed={on}
                  onClick={() => {
                    pick(r.id)
                    goStep(2)
                  }}
                  className={`flex min-h-16 items-center gap-3 rounded-[18px] border-0 px-3 py-2 text-left active:bg-mute ${on ? 'bg-page' : 'bg-transparent'}`}
                >
                  <Avatar text={r.badge} index={i} size={44} />
                  <span className="flex min-w-0 flex-1 flex-col gap-0.5">
                    <span className="truncate text-[15px] font-semibold">{r.name}</span>
                    <span className="font-mono text-xs text-ink-3">{r.mask}</span>
                  </span>
                  <span className={on ? 'text-ok-fg' : 'text-[#9a9ea6]'}>
                    <Icon name={on ? 'check' : 'chev'} />
                  </span>
                </button>
              )
            })}
            {matches.length === 0 && <p className="m-0 px-3 py-4 text-sm text-ink-3">Aucun destinataire ne correspond. Saisissez un numéro de compte.</p>}
          </section>
        </div>
      )}

      {ms === 2 && (
        <div className={`flex flex-col gap-4 ${anim}`}>
          {toChip}
          <section aria-labelledby="h-wa" className="flex flex-col gap-2">
            <h3 id="h-wa" className="m-0 text-sm font-semibold text-ink-2">
              Depuis le compte
            </h3>
            <div role="group" aria-label="Compte à débiter" className="-mx-1 flex gap-3 overflow-x-auto p-1 pb-2.5">
              {accountCards('sm')}
            </div>
          </section>
          <section aria-label="Montant" className="flex flex-col gap-3.5 rounded-3xl bg-white p-[18px] shadow-card">
            {amountBox(true)}
            <span className="text-center text-[13px] text-ink-3">{avail}</span>
          </section>
          {errBox}
          {next('Continuer', () => check(['amount']) && goStep(3))}
        </div>
      )}

      {ms === 3 && (
        <div className={`flex flex-col gap-4 ${anim}`}>
          {toChip}
          <section aria-label="Libellé" className="flex flex-col gap-3.5 rounded-3xl bg-white p-[18px] shadow-card">
            {labelField}
          </section>
          {errBox}
          {next('Vérifier le virement', () => check(['to', 'amount']) && goStep(4))}
        </div>
      )}

      {ms === 4 && toRec && (
        <div className={`flex flex-col gap-4 ${anim}`}>
          <section aria-label="Récapitulatif" className="flex flex-col gap-2.5 rounded-3xl bg-white px-[18px] pt-5 pb-2 shadow-card">
            <div className="flex flex-col items-center gap-2.5 pt-1 pb-2.5">
              <Avatar text={toRec.badge} index={toIndex} size={56} />
              <span className="text-sm font-medium text-ink-3">Vous envoyez à {toRec.name}</span>
              <span className="tnum text-[44px] leading-none font-bold tracking-[-0.03em]">{formatMoney(amount, src.currency)}</span>
            </div>
            <Recap rows={recapRows.filter(([k]) => k !== 'Vers')} />
          </section>
          <SlideToConfirm ariaLabel={`${cta} à ${toRec.name}. Faites glisser ou appuyez sur Entrée.`} onConfirm={() => void execute()} />
          <span className="text-center text-xs text-ink-3">Faites glisser jusqu’au bout pour confirmer</span>
        </div>
      )}
    </div>
  )
}

function SearchBox({ value, onChange, placeholder, label }: { value: string; onChange: (v: string) => void; placeholder: string; label: string }) {
  return (
    <label className="relative flex items-center">
      <span className="absolute left-4 text-ink-3">
        <Icon name="search" />
      </span>
      <input type="search" value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder} aria-label={label} className="search bg-soft focus:bg-white" />
    </label>
  )
}

function Recap({ rows }: { rows: [string, string][] }) {
  return (
    <dl className="m-0 flex flex-col">
      {rows.map(([k, v]) => (
        <div key={k} className="flex justify-between gap-4 border-t border-mute py-3">
          <dt className="text-sm text-ink-3">{k}</dt>
          <dd className="m-0 text-right text-[15px] font-semibold">{v}</dd>
        </div>
      ))}
    </dl>
  )
}

const KNOB = 56
const PAD = 4

/** « Glisser pour envoyer » (maquette mobile). Clavier : Entrée / Espace / flèche droite. */
function SlideToConfirm({ ariaLabel, onConfirm }: { ariaLabel: string; onConfirm: () => void }) {
  const track = useRef<HTMLDivElement>(null)
  const start = useRef(0)
  const [x, setX] = useState(0)
  const [drag, setDrag] = useState(false)
  const [done, setDone] = useState(false)
  const [span, setSpan] = useState(240)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  // Quitter l'écran pendant l'animation de confirmation ne doit pas envoyer le virement.
  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current)
    },
    [],
  )
  const maxX = () => (track.current ? track.current.clientWidth - 2 * PAD - KNOB : 240)

  function finish() {
    if (done) return
    setDone(true)
    setDrag(false)
    setX(maxX())
    timer.current = setTimeout(onConfirm, 750)
  }
  function down(e: RPointerEvent<HTMLButtonElement>) {
    if (done) return
    start.current = e.clientX - x
    setSpan(maxX())
    e.currentTarget.setPointerCapture?.(e.pointerId)
    setDrag(true)
  }
  function move(e: RPointerEvent<HTMLButtonElement>) {
    if (drag) setX(Math.max(0, Math.min(span, e.clientX - start.current)))
  }
  function up() {
    if (!drag) return
    if (x >= span * 0.85) finish()
    else {
      setDrag(false)
      setX(0)
    }
  }

  const progress = done ? 1 : x / Math.max(1, span)
  const ease = 'cubic-bezier(.2,.8,.2,1)'
  return (
    <div ref={track} className="relative h-16 touch-none overflow-hidden rounded-full bg-[#e6e8eb] p-1 select-none">
      <span
        aria-hidden
        className={`absolute inset-y-0 left-0 rounded-full ${done ? 'bg-ok-fg' : 'bg-night'}`}
        style={{ width: Math.round(x) + 62, transition: drag ? 'none' : `width .45s ${ease}, background .3s` }}
      />
      <span
        aria-hidden
        className="absolute inset-0 flex animate-shine items-center justify-center bg-[linear-gradient(100deg,#6b6f76_0%,#6b6f76_42%,#121316_50%,#6b6f76_58%,#6b6f76_100%)] bg-[length:220%_100%] bg-clip-text pl-[52px] text-base font-semibold text-transparent"
        style={{ opacity: Math.max(0, 1 - progress * 1.6) }}
      >
        Glisser pour envoyer
      </span>
      <span aria-hidden className="absolute inset-0 flex items-center justify-center text-base font-semibold text-white transition-opacity delay-150" style={{ opacity: done ? 1 : 0 }}>
        Envoi…
      </span>
      <button
        type="button"
        aria-label={ariaLabel}
        onPointerDown={down}
        onPointerMove={move}
        onPointerUp={up}
        onPointerCancel={up}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ' || e.key === 'ArrowRight') {
            e.preventDefault()
            finish()
          }
        }}
        className={`relative z-[1] grid h-14 w-14 cursor-grab touch-none place-items-center rounded-full border-0 bg-white shadow-[0_4px_14px_-4px_rgba(18,19,22,.45)] ${done ? 'text-ok-fg' : 'text-ink'}`}
        style={{ transform: `translateX(${Math.round(x)}px)`, transition: drag ? 'none' : `transform .45s ${ease}` }}
      >
        {done ? (
          <span className="grid animate-pop">
            <Icon name="check" size={24} />
          </span>
        ) : (
          <Icon name="chev" size={24} />
        )}
      </button>
    </div>
  )
}

function ResultCard({
  outcome,
  amount,
  src,
  toName,
  onCopy,
  onView,
  onNew,
  onEditAmount,
  onHome,
  onHistory,
  onRetry,
  onCancel,
}: {
  outcome: Outcome
  amount: number
  src: Account
  toName: string
  onCopy: (ref: string) => void
  onView: (txId: string) => void
  onNew: () => void
  onEditAmount: () => void
  onHome: () => void
  onHistory: () => void
  onRetry: () => void
  onCancel: () => void
}) {
  const money = formatMoney(amount, src.currency)
  const apiRef = outcome.kind !== 'success' && outcome.error instanceof ApiError ? outcome.error.requestId : null
  const ref = outcome.kind === 'success' ? (outcome.tx.requestId ?? `#${outcome.tx.id}`) : apiRef

  let view: { icon: 'check' | 'x' | 'alert'; tone: string; title: string; text: ReactNode; a: [string, () => void]; b: [string, () => void] }
  switch (outcome.kind) {
    case 'success':
      view = {
        icon: 'check',
        tone: 'bg-ok-bg text-ok-fg',
        title: 'Virement envoyé',
        text: `${money} ont été envoyés au ${toName.toLowerCase()}.`,
        a: ['Voir l’opération', () => onView(outcome.tx.id)],
        b: ['Nouveau virement', onNew],
      }
      break
    case 'balance':
      view = {
        icon: 'x',
        tone: 'bg-ko-bg text-ko-fg',
        title: 'Virement refusé — solde insuffisant',
        text: `Le montant de ${money} dépasse le solde disponible de ${formatMoney(src.balance, src.currency)} sur le ${accountName(src.id).toLowerCase()}.`,
        a: ['Modifier le montant', onEditAmount],
        b: ['Retour à l’accueil', onHome],
      }
      break
    case 'limit':
    case 'refused':
      view = {
        icon: 'x',
        tone: 'bg-ko-bg text-ko-fg',
        title: outcome.kind === 'limit' ? 'Virement refusé — plafond dépassé' : 'Virement refusé',
        text: outcome.error ? userMessage(outcome.error) : 'La banque a refusé ce virement.',
        a: ['Modifier le montant', onEditAmount],
        b: ['Retour à l’accueil', onHome],
      }
      break
    default: {
      // Timeout / coupure réseau : le serveur a pu exécuter le virement sans que la réponse arrive. Pas de clé
      // d'idempotence côté payment-api : on renvoie vers l'historique plutôt que de risquer un double débit.
      // Un 5xx explicite (transaction annulée côté ledger) garde « Réessayer ».
      const unknown = outcome.error instanceof ApiError && outcome.error.isNetwork
      view = unknown
        ? {
            icon: 'alert',
            tone: 'bg-warn-bg text-warn-fg',
            title: 'Statut du virement inconnu',
            text: 'Le serveur n’a pas répondu à temps : le virement a pu être exécuté. Vérifiez votre historique avant d’en émettre un nouveau.',
            a: ['Voir l’historique', onHistory],
            b: ['Retour à l’accueil', onHome],
          }
        : {
            icon: 'alert',
            tone: 'bg-warn-bg text-warn-fg',
            title: 'Le virement n’a pas pu être transmis',
            text: `${userMessage(outcome.error)} Aucun montant n’a été débité, vous pouvez réessayer.`,
            a: ['Réessayer', onRetry],
            b: ['Annuler', onCancel],
          }
    }
  }

  return (
    <div
      role={outcome.kind === 'success' ? 'status' : 'alert'}
      aria-live="polite"
      className="mx-auto mt-3 flex w-full max-w-[560px] flex-col items-center gap-3.5 rounded-[28px] bg-white px-6 pt-9 pb-6 text-center shadow-card"
    >
      <span className={`grid h-[88px] w-[88px] place-items-center rounded-full ${view.tone}`}>
        <Icon name={view.icon} size={28} />
      </span>
      <h2 className="m-0 mt-1.5 text-2xl font-bold tracking-[-0.02em] text-balance">{view.title}</h2>
      <p className="m-0 max-w-[400px] text-[15px] leading-normal text-pretty text-ink-2">{view.text}</p>
      {ref && (
        <button type="button" onClick={() => onCopy(ref)} aria-label="Copier la référence" className="flex min-h-11 items-center gap-2 rounded-xl border-0 bg-page px-3.5 font-mono text-[13px]">
          {ref} <Icon name="copy" size={16} />
        </button>
      )}
      <div className="mt-2.5 grid w-full gap-2.5 [grid-template-columns:repeat(auto-fit,minmax(180px,1fr))]">
        <button type="button" onClick={view.b[1]} className="btn-ghost text-[15px]">
          {view.b[0]}
        </button>
        <button type="button" onClick={view.a[1]} className="btn-primary text-[15px]">
          {view.a[0]}
        </button>
      </div>
    </div>
  )
}
