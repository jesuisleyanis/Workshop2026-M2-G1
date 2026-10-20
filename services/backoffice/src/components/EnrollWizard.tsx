import { useEffect, useRef, useState, type FormEvent } from 'react'
import { createUser, enrollFace, type AgentRole } from '../api/admin'
import type { Pose } from '../api/auth'
import { ApiError } from '../api/http'
import { adminErrorText } from '../lib/adminErrors'
import { ROLES, ROLE_LABELS, validateCredentials, type CredentialErrors } from '../lib/validation'
import { EnrollCapture } from './EnrollCapture'
import { Field } from './Field'

// Assistant « Nouvel agent » (et ré-enrôlement) : 1) compte, 2) scanner 3 poses, 3) récapitulatif
// et validation. Le compte n'est créé qu'à la validation finale, jamais avant d'avoir des photos ;
// si l'enrôlement est ensuite rejeté (422), la série est refaite SANS recréer le compte.

type Step = 'form' | 'capture'

export function EnrollWizard({
  token,
  reenroll,
  takenUsernames = [],
  onClose,
}: {
  token: string
  /** Identifiant d'un compte existant : on saute le formulaire et on ne fait que ré-enrôler. */
  reenroll?: string
  /** Identifiants déjà connus (contrôle immédiat avant la capture). */
  takenUsernames?: string[]
  /** `refresh` : la liste des agents a changé (compte créé et/ou visage enrôlé). */
  onClose: (refresh: boolean) => void
}) {
  const [step, setStep] = useState<Step>(reenroll ? 'capture' : 'form')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [role, setRole] = useState<AgentRole>('operator')
  const [errors, setErrors] = useState<CredentialErrors>({})
  const createdRef = useRef(false)
  const headingRef = useRef<HTMLHeadingElement>(null)

  useEffect(() => {
    headingRef.current?.focus()
  }, [step])

  function onContinue(e: FormEvent) {
    e.preventDefault()
    const name = username.trim()
    const found = validateCredentials({ username: name, password, confirm })
    if (!found.username && takenUsernames.some((u) => u.toLowerCase() === name.toLowerCase())) {
      found.username = adminErrorText(new ApiError(409, 'username_taken', ''))
    }
    setErrors(found)
    if (Object.keys(found).length > 0) return
    setUsername(name)
    setStep('capture')
  }

  async function submit(poses: Record<Pose, string>) {
    const target = reenroll ?? username
    if (!reenroll && !createdRef.current) {
      try {
        await createUser(token, { username, password, role })
        createdRef.current = true
        setPassword('')
        setConfirm('')
      } catch (err) {
        if (err instanceof ApiError && err.status === 409 && err.code === 'username_taken') {
          setErrors({ username: adminErrorText(err) })
          setStep('form')
          return
        }
        throw err
      }
    }
    await enrollFace(token, target, poses)
    onClose(true)
  }

  const title = reenroll ? `Ré-enrôler ${reenroll}` : 'Nouvel agent'
  const stepLabel = reenroll ? 'Capture du visage' : step === 'form' ? 'Étape 1 sur 3 — compte' : 'Étape 2 sur 3 — visage, puis validation'

  return (
    <div className="fixed inset-0 z-50 grid place-items-start justify-items-center overflow-y-auto bg-night/60 p-4 sm:place-items-center">
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="wizard-title"
        className="flex w-full max-w-[560px] flex-col gap-5 rounded-2xl border border-line bg-white p-6"
      >
        <div className="flex flex-col gap-1.5">
          <h2 id="wizard-title" ref={headingRef} tabIndex={-1} className="text-[22px] font-semibold tracking-[-0.02em] outline-none">
            {title}
          </h2>
          <p className="text-sm text-ink-3">{stepLabel}</p>
        </div>

        {step === 'form' ? (
          <form onSubmit={onContinue} noValidate className="flex flex-col gap-4">
            <Field
              label="Identifiant"
              autoComplete="off"
              autoCapitalize="none"
              spellCheck={false}
              value={username}
              error={errors.username}
              onChange={(e) => setUsername(e.target.value)}
            />
            <Field
              label="Mot de passe"
              type="password"
              autoComplete="new-password"
              value={password}
              error={errors.password}
              onChange={(e) => setPassword(e.target.value)}
            />
            <Field
              label="Confirmation du mot de passe"
              type="password"
              autoComplete="new-password"
              value={confirm}
              error={errors.confirm}
              onChange={(e) => setConfirm(e.target.value)}
            />
            <div className="flex flex-col gap-2">
              <label htmlFor="wizard-role" className="text-[13px] font-medium">
                Rôle
              </label>
              <select id="wizard-role" className="field" value={role} onChange={(e) => setRole(e.target.value as AgentRole)}>
                {ROLES.map((r) => (
                  <option key={r} value={r}>
                    {ROLE_LABELS[r]}
                  </option>
                ))}
              </select>
            </div>
            <div className="flex justify-end gap-2.5">
              <button type="button" className="btn-ghost" onClick={() => onClose(false)}>
                Annuler
              </button>
              <button type="submit" className="btn-primary">
                Continuer
              </button>
            </div>
          </form>
        ) : (
          <EnrollCapture onSubmit={submit} onCancel={() => onClose(createdRef.current)} />
        )}
      </div>
    </div>
  )
}
