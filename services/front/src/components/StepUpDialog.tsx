import { useEffect, useRef, useState, type FormEvent } from 'react'
import { ApiError } from '../api/errors'
import { useAuth } from '../hooks/useAuth'
import { userMessage } from '../lib/errorMessages'
import { Icon } from './icons'

/** Seuil indicatif affiché (le serveur reste l'autorité : STEP_UP_THRESHOLD_CENTS). */

/**
 * D15 — Confirmation renforcée d'un gros virement (#51). `onDone(true)` après une
 * ré-authentification réussie (l'appelant rejoue la requête), `onDone(false)` si annulée.
 * Le mot de passe ne vit que dans l'état de la modale, vidé après chaque essai.
 */
export function StepUpDialog({ onDone }: { onDone: (ok: boolean) => void }) {
  const { stepUp } = useAuth()
  const [password, setPassword] = useState('')
  const [err, setErr] = useState<string | null>(null)
  const [locked, setLocked] = useState(false)
  const [busy, setBusy] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)
  const done = useRef(onDone)
  useEffect(() => {
    done.current = onDone
  })
  useEffect(() => {
    inputRef.current?.focus()
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && done.current(false)
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    if (!password || busy || locked) return
    setBusy(true)
    setErr(null)
    const attempt = password
    setPassword('')
    try {
      await stepUp(attempt)
      onDone(true)
    } catch (e2) {
      if (e2 instanceof ApiError && e2.isRateLimited) {
        setLocked(true)
        setErr('Trop de tentatives. Patientez une minute avant de réessayer.')
      } else if (e2 instanceof ApiError && e2.code === 'invalid_credentials') {
        setErr('Mot de passe incorrect.')
        inputRef.current?.focus()
      } else {
        setErr(userMessage(e2))
      }
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-[rgba(18,19,22,.5)] p-3 lg:items-center lg:p-6">
      <form
        role="dialog"
        aria-modal="true"
        aria-labelledby="stepup-title"
        onSubmit={(e) => void submit(e)}
        className="flex w-full max-w-[440px] flex-col gap-3.5 rounded-[28px] bg-white p-6 shadow-[0_30px_60px_-20px_rgba(18,19,22,.5)]"
      >
        <span className="grid h-[52px] w-[52px] place-items-center rounded-2xl bg-page">
          <Icon name="lock" size={28} />
        </span>
        <h2 id="stepup-title" className="m-0 text-[21px] font-bold tracking-[-0.02em]">
          Confirmation renforcée
        </h2>
        <p className="m-0 text-[15px] leading-normal text-ink-2">
          Pour ce montant important, confirmez votre mot de passe (le seuil est fixé par la banque).
        </p>
        <label className="flex flex-col gap-1.5 text-sm font-medium text-ink-2">
          Mot de passe
          <input
            ref={inputRef}
            type="password"
            autoComplete="current-password"
            value={password}
            disabled={locked}
            onChange={(e) => setPassword(e.target.value)}
            aria-invalid={err !== null}
            className="field"
          />
        </label>
        {err && (
          <p role="alert" className="m-0 rounded-[14px] bg-ko-bg px-4 py-3 text-sm font-medium text-ko-fg">
            {err}
          </p>
        )}
        <div className="mt-1.5 grid grid-cols-2 gap-2.5">
          <button type="button" onClick={() => onDone(false)} className="btn-ghost h-[52px] text-[15px]">
            {locked ? 'Fermer' : 'Annuler'}
          </button>
          <button type="submit" disabled={busy || locked || !password} className="btn-primary h-[52px] text-[15px]">
            {busy ? 'Vérification…' : 'Confirmer'}
          </button>
        </div>
      </form>
    </div>
  )
}
