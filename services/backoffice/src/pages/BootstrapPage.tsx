import { useState, type FormEvent } from 'react'
import { ApiError } from '../api/http'
import { bootstrap, type Pose } from '../api/auth'
import { Brand } from '../components/Brand'
import { EnrollCapture } from '../components/EnrollCapture'
import { Field } from '../components/Field'
import { adminErrorText } from '../lib/adminErrors'
import { validateCredentials, type CredentialErrors } from '../lib/validation'

// Initialisation du back-office : aucun administrateur n'existe encore. Le jeton d'initialisation
// (secret remis à l'exploitant) autorise la création du premier admin, enrôlé par ses trois poses.
// Le jeton n'est contrôlé que par le serveur, à la validation finale.

type Step = 'form' | 'capture' | 'done'

export function BootstrapPage({ onDone }: { onDone: () => void }) {
  const [step, setStep] = useState<Step>('form')
  const [token, setToken] = useState('')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [errors, setErrors] = useState<CredentialErrors & { token?: string }>({})
  const [notice, setNotice] = useState<string | null>(null)

  function onContinue(e: FormEvent) {
    e.preventDefault()
    const name = username.trim()
    const found: CredentialErrors & { token?: string } = validateCredentials({ username: name, password, confirm })
    if (!token.trim()) found.token = 'Jeton d’initialisation requis.'
    setErrors(found)
    setNotice(null)
    if (Object.keys(found).length > 0) return
    setUsername(name)
    setStep('capture')
  }

  async function submit(poses: Record<Pose, string>) {
    try {
      await bootstrap({ token: token.trim(), username, password, poses })
    } catch (err) {
      if (err instanceof ApiError && err.code === 'bootstrap_denied') {
        // Jeton refusé : retour au formulaire pour le corriger (les photos sont à refaire).
        setToken('')
        setNotice(adminErrorText(err))
        setStep('form')
        return
      }
      throw err
    }
    setToken('')
    setPassword('')
    setConfirm('')
    setStep('done')
  }

  return (
    <div data-testid="bootstrap-page" className="grid min-h-screen place-items-start justify-items-center p-4 sm:place-items-center sm:p-6">
      <div className={`flex w-full flex-col gap-6 ${step === 'capture' ? 'max-w-[600px]' : 'max-w-[460px]'}`}>
        <Brand />
        <div className="flex flex-col gap-5 rounded-2xl border border-line bg-frame p-6">
          <div className="flex flex-col gap-1.5">
            <h1 className="text-[26px] font-semibold tracking-[-0.03em]">Initialisation du back-office</h1>
            <p className="text-[15px] text-ink-3">
              {step === 'form' && 'Aucun administrateur n’existe. Créez le premier compte avec le jeton remis à l’exploitant.'}
              {step === 'capture' && 'Enrôlez le visage du premier administrateur : face, gauche, droite.'}
              {step === 'done' && 'Le back-office est prêt.'}
            </p>
          </div>

          {step === 'form' && (
            <form onSubmit={onContinue} noValidate className="flex flex-col gap-4">
              {notice && (
                <div role="alert" className="rounded-xl bg-ko-bg px-3.5 py-3 text-sm text-ko-fg">
                  {notice}
                </div>
              )}
              <Field
                label="Jeton d’initialisation"
                type="password"
                autoComplete="off"
                spellCheck={false}
                value={token}
                error={errors.token}
                onChange={(e) => setToken(e.target.value)}
              />
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
              <button type="submit" className="btn-primary h-[54px] text-base">
                Continuer
              </button>
            </form>
          )}

          {step === 'capture' && <EnrollCapture submitLabel="Valider l’enrôlement" onSubmit={submit} onCancel={() => setStep('form')} />}

          {step === 'done' && (
            <>
              <div role="status" className="rounded-xl bg-ok-bg px-3.5 py-3 text-sm text-ok-fg">
                Premier administrateur créé et visage enrôlé. Vous pouvez vous connecter.
              </div>
              <button type="button" className="btn-primary h-[54px] text-base" onClick={onDone}>
                Aller à la connexion
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
