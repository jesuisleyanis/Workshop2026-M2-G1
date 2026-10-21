import { useState, type FormEvent } from 'react'
import { Navigate, useLocation, useNavigate } from 'react-router-dom'
import type { LoginRedirectState } from '../components/ProtectedRoute'
import { Brand } from '../components/ui'
import { useAuth } from '../hooks/useAuth'
import { userMessage } from '../lib/errorMessages'

// Raccourcis de démo : identifiants seulement. Les mots de passe ne sont jamais embarqués
// dans le bundle (servi publiquement derrière le WAF, visible depuis le PC Attaquant).
const DEMO_USERS = ['demo01', 'demo02']

export function LoginPage() {
  const { isAuthenticated, login, notice } = useAuth()
  const navigate = useNavigate()
  const from = (useLocation().state as LoginRedirectState | null)?.from
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  if (isAuthenticated) return <Navigate to={from ?? '/'} replace />

  const info = notice ?? (from && from !== '/' ? 'Connectez-vous pour accéder à cette page.' : null)

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    if (!username.trim() || !password) {
      setError('Renseignez votre identifiant et votre mot de passe.')
      return
    }
    setError(null)
    setSubmitting(true)
    try {
      await login(username.trim(), password)
      navigate(from ?? '/', { replace: true })
    } catch (err) {
      setError(userMessage(err))
      setSubmitting(false)
    }
  }

  const edit = (set: (v: string) => void) => (v: string) => {
    set(v)
    setError(null)
  }

  return (
    <div className="grid min-h-dvh bg-white [grid-template-columns:repeat(auto-fit,minmax(min(100%,380px),1fr))]">
      <div className="flex flex-col justify-between gap-7 bg-[linear-gradient(160deg,#2a2c32_0%,#121316_60%)] p-[clamp(24px,4vw,48px)] text-white">
        <Brand inverted />
        <div className="flex flex-col gap-3.5">
          <p className="m-0 text-balance text-[clamp(32px,4vw,52px)] leading-[1.02] font-semibold tracking-[-0.04em]">Votre argent, toujours disponible.</p>
          <p className="m-0 max-w-[360px] text-[15px] leading-normal text-ink-4">Démonstrateur pédagogique. Toutes les données sont fictives.</p>
        </div>
        <div aria-hidden className="flex aspect-[1.6] max-w-[320px] flex-col justify-between rounded-[22px] border border-[#3a3d44] bg-[#23252b] p-5">
          <div className="h-7 w-[38px] rounded-[7px] bg-[linear-gradient(135deg,#d2d4d8,#8a8e95)]" />
          <span className="font-mono text-[15px] tracking-[0.06em]">•••• •••• •••• 8160</span>
        </div>
      </div>

      <div className="flex items-center justify-center p-[clamp(24px,5vw,64px)]">
        <form onSubmit={onSubmit} noValidate aria-labelledby="login-title" className="flex w-full max-w-[380px] flex-col gap-[18px]">
          <div className="flex flex-col gap-1.5">
            <h1 id="login-title" className="m-0 text-[30px] font-bold tracking-[-0.03em]">Connexion</h1>
            <p className="m-0 text-[15px] text-ink-3">Accédez à votre espace client.</p>
          </div>
          {info && !error && <div role="status" className="rounded-[14px] bg-warn-bg px-3.5 py-3 text-sm text-[#7a4d00]">{info}</div>}
          {error && <div role="alert" className="rounded-[14px] bg-ko-bg px-3.5 py-3 text-sm font-medium text-ko-fg">{error}</div>}

          <label className="flex flex-col gap-2 text-sm font-semibold">
            Identifiant
            <input className="field h-[54px] rounded-2xl text-base font-normal" autoComplete="username" placeholder="demo01" value={username} onChange={(e) => edit(setUsername)(e.target.value)} />
          </label>
          <div className="flex flex-col gap-2">
            <label htmlFor="password" className="text-sm font-semibold">Mot de passe</label>
            <div className="relative flex">
              <input
                id="password"
                className="field h-[54px] rounded-2xl pr-24 text-base"
                type={showPassword ? 'text' : 'password'}
                autoComplete="current-password"
                value={password}
                onChange={(e) => edit(setPassword)(e.target.value)}
              />
              <button
                type="button"
                onClick={() => setShowPassword((s) => !s)}
                aria-pressed={showPassword}
                className="absolute top-[5px] right-[5px] h-11 rounded-xl border-0 bg-transparent px-3 text-sm font-semibold text-ink-2"
              >
                {showPassword ? 'Masquer' : 'Afficher'}
              </button>
            </div>
          </div>

          <button type="submit" disabled={submitting} className="btn-primary h-14">
            {submitting ? 'Connexion…' : 'Se connecter'}
          </button>

          <div className="flex flex-col gap-2.5 border-t border-mute pt-3">
            <span className="text-xs text-ink-3">Comptes de démonstration</span>
            <div className="flex flex-wrap gap-2">
              {DEMO_USERS.map((u) => (
                <button
                  key={u}
                  type="button"
                  onClick={() => edit(setUsername)(u)}
                  className="min-h-11 rounded-xl border-[1.5px] border-line bg-white px-3.5 text-sm font-semibold hover:border-ink"
                >
                  {u}
                </button>
              ))}
            </div>
          </div>
        </form>
      </div>
    </div>
  )
}
