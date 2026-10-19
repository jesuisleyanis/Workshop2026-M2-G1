import { useState, type FormEvent } from 'react'
import { Navigate, useNavigate } from 'react-router-dom'
import { Field } from '../components/Field'
import { ErrorBanner } from '../components/ErrorBanner'
import { useAuth } from '../hooks/useAuth'

export function LoginPage() {
  const { isAuthenticated, login } = useAuth()
  const navigate = useNavigate()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<unknown>(null)

  if (isAuthenticated) return <Navigate to="/" replace />

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    setSubmitting(true)
    try {
      await login(username.trim(), password)
      navigate('/', { replace: true })
    } catch (err) {
      setError(err)
      setSubmitting(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-100 px-4">
      <form onSubmit={onSubmit} className="w-full max-w-sm space-y-5 rounded-2xl bg-white p-8 shadow-md ring-1 ring-slate-200" aria-labelledby="login-title">
        <div>
          <h1 id="login-title" className="text-2xl font-semibold text-teal-800">Connexion</h1>
          <p className="mt-1 text-sm text-slate-500">Plateforme de paiement fictive — données de démonstration.</p>
        </div>
        <Field label="Identifiant" value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" required />
        <Field label="Mot de passe" type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" required />
        {error !== null && <ErrorBanner error={error} />}
        <button type="submit" disabled={submitting || !username || !password} className="w-full rounded-lg bg-teal-700 px-4 py-2.5 font-medium text-white hover:bg-teal-800 disabled:cursor-not-allowed disabled:opacity-60">
          {submitting ? 'Connexion…' : 'Se connecter'}
        </button>
      </form>
    </div>
  )
}
