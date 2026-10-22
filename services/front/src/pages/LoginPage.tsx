import { useState, type FormEvent } from 'react'
import { Navigate, useLocation, useNavigate } from 'react-router-dom'
import type { LoginRedirectState } from '../components/ProtectedRoute'
import { Logo } from '../components/icons'
import { Brand } from '../components/ui'
import { useAuth } from '../hooks/useAuth'
import { userMessage } from '../lib/errorMessages'

// Raccourcis de démo : identifiants seulement. Les mots de passe ne sont jamais embarqués
// dans le bundle (servi publiquement derrière le WAF, visible depuis le PC Attaquant).
// demo01/demo02 : comptes de service (verify_tx, trafic normal), sans plafond ; demo03 : client avec plafond (#46).
const DEMO_USERS = ['demo01', 'demo02', 'demo03']

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
        <DemoCard />
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

/** Carte bancaire décorative (fictive) de l'écran de connexion : logo, puce, sans-contact, titulaire, expiration. */
function DemoCard() {
  return (
    <div
      aria-hidden
      className="relative flex aspect-[1.586] w-full max-w-[340px] flex-col justify-between overflow-hidden rounded-[22px] border border-white/10 bg-[linear-gradient(135deg,#3a3d45_0%,#1b1c21_55%,#0d0e11_100%)] p-5 shadow-[0_30px_50px_-25px_rgba(0,0,0,.9)]"
    >
      {/* Reflets */}
      <span className="absolute -top-24 -right-16 h-64 w-64 rounded-full border border-white/10" />
      <span className="absolute -top-10 -right-4 h-40 w-40 rounded-full border border-white/[.07]" />
      <span className="absolute -bottom-28 -left-20 h-56 w-56 rounded-full bg-violet/20 blur-3xl" />
      <span className="absolute -right-6 -bottom-10 text-white/[.04]">
        <Logo size={190} />
      </span>

      <div className="relative flex items-start justify-between">
        <span className="flex items-center gap-2">
          <Logo size={22} />
          <span className="text-[15px] font-semibold tracking-[-0.01em]">Résilience</span>
        </span>
        <span className="text-[11px] font-semibold tracking-[0.18em] text-white/60 uppercase">Premier</span>
      </div>

      <div className="relative flex items-center gap-3">
        <svg viewBox="0 0 44 34" className="h-[30px] w-[40px]">
          <defs>
            <linearGradient id="chip" x1="0" y1="0" x2="1" y2="1">
              <stop offset="0" stopColor="#f1f2f4" />
              <stop offset=".5" stopColor="#b9bcc2" />
              <stop offset="1" stopColor="#8a8e95" />
            </linearGradient>
          </defs>
          <rect width="44" height="34" rx="7" fill="url(#chip)" />
          <path d="M0 12h13M0 22h13M31 12h13M31 22h13M13 0v34M31 0v34M13 17h18" stroke="#6f737a" strokeWidth="1.2" fill="none" />
        </svg>
        <svg viewBox="0 0 24 24" className="h-6 w-6 text-white/70" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round">
          <path d="M8.5 8.5a5 5 0 0 1 0 7M12 6a8.5 8.5 0 0 1 0 12M15.5 3.5a12 12 0 0 1 0 17" />
        </svg>
      </div>

      <span className="relative font-mono text-[17px] tracking-[0.14em]">•••• •••• •••• 8160</span>

      <div className="relative flex items-end justify-between">
        <span className="flex gap-6 text-[11px]">
          <span className="flex flex-col gap-0.5">
            <span className="tracking-[0.12em] text-white/50 uppercase">Titulaire</span>
            <span className="text-[13px] font-semibold tracking-[0.06em]">CLIENT DÉMO</span>
          </span>
          <span className="flex flex-col gap-0.5">
            <span className="tracking-[0.12em] text-white/50 uppercase">Expire</span>
            <span className="tnum text-[13px] font-semibold">12/29</span>
          </span>
        </span>
        <span className="flex">
          <span className="h-7 w-7 rounded-full bg-white/80" />
          <span className="-ml-3 h-7 w-7 rounded-full bg-violet/90 mix-blend-screen" />
        </span>
      </div>
    </div>
  )
}
