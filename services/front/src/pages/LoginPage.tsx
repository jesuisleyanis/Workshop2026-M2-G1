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
    <div className="grid min-h-screen [grid-template-columns:repeat(auto-fit,minmax(min(100%,400px),1fr))]">
      <div className="flex flex-col justify-between gap-12 bg-night p-[clamp(28px,4vw,48px)] text-[#f3f4f6]">
        <Brand inverted />
        <div className="flex flex-col gap-4">
          <p className="text-balance text-[clamp(36px,4.4vw,58px)] font-semibold leading-none tracking-[-0.04em]">Vos virements, sans surprise.</p>
          <p className="max-w-[380px] text-[15px] leading-relaxed text-[#a7abb3]">
            Plateforme de démonstration de la Banque Résilience. Toutes les données affichées sont factices.
          </p>
        </div>
        <div className="flex aspect-[1.6] max-w-[360px] flex-col justify-between rounded-[22px] border border-[#33363d] bg-night-2 p-5" aria-hidden>
          <div className="flex items-center justify-between">
            <div className="h-7 w-[38px] rounded-[7px] bg-[#3a3d45]" />
            <span className="text-xs text-[#a7abb3]">Démo</span>
          </div>
          <div className="flex flex-col gap-1.5">
            <span className="font-mono text-[15px] tracking-wide">FR76 •••• •••• •••• 0142</span>
            <span className="text-xs text-[#a7abb3]">Banque Résilience</span>
          </div>
        </div>
      </div>

      <div className="flex items-center justify-center bg-white p-[clamp(28px,5vw,64px)]">
        <form onSubmit={onSubmit} noValidate aria-labelledby="login-title" className="flex w-full max-w-[380px] flex-col gap-5">
          <div className="flex flex-col gap-1.5">
            <h1 id="login-title" className="text-[30px] font-semibold tracking-[-0.03em]">Connexion</h1>
            <p className="text-[15px] text-ink-3">Accédez à votre espace client.</p>
          </div>
          {info && <div role="status" className="rounded-xl bg-warn-bg px-3.5 py-3 text-sm text-warn-fg">{info}</div>}
          {error && <div role="alert" className="rounded-xl bg-ko-bg px-3.5 py-3 text-sm text-ko-fg">{error}</div>}

          <label className="flex flex-col gap-2">
            <span className="text-[13px] font-medium">Identifiant</span>
            <input className="field" autoComplete="username" placeholder="demo01" value={username} onChange={(e) => edit(setUsername)(e.target.value)} />
          </label>
          <div className="flex flex-col gap-2">
            <label htmlFor="password" className="text-[13px] font-medium">Mot de passe</label>
            <div className="relative">
              <input
                id="password"
                className="field pr-24"
                type={showPassword ? 'text' : 'password'}
                autoComplete="current-password"
                placeholder="••••••••"
                value={password}
                onChange={(e) => edit(setPassword)(e.target.value)}
              />
              <button
                type="button"
                onClick={() => setShowPassword((s) => !s)}
                aria-pressed={showPassword}
                className="absolute right-2 top-2 h-9 cursor-pointer rounded-[10px] px-3 text-[13px] text-ink-2 hover:bg-[#eceef1]"
              >
                {showPassword ? 'Masquer' : 'Afficher'}
              </button>
            </div>
          </div>

          <button type="submit" disabled={submitting} className="btn-primary h-[54px] text-base">
            {submitting ? 'Connexion…' : 'Se connecter'}
          </button>

          <div className="flex flex-col gap-2.5 border-t border-[#eceef1] pt-3">
            <span className="text-xs text-ink-3">Comptes de démonstration</span>
            <div className="flex flex-wrap gap-2">
              {DEMO_USERS.map((u) => (
                <button
                  key={u}
                  type="button"
                  onClick={() => edit(setUsername)(u)}
                  className="min-h-11 cursor-pointer rounded-xl border-[1.5px] border-line px-3.5 text-sm font-semibold hover:border-night"
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
