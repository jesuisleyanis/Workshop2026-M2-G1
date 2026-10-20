import { useEffect, useState } from 'react'
import { LoginPage } from './pages/LoginPage'
import { bootstrapStatus, type TokenResult } from './api/auth'
import { clearSession, setSession as storeSession } from './lib/session'
import { BootstrapPage } from './pages/BootstrapPage'
import { HomePage } from './pages/HomePage'

type Gate = 'loading' | 'bootstrap' | 'login'

// Coquille du back-office :
//  1. `bootstrapStatus()` au montage : aucun admin => écran de bootstrap du premier admin ;
//  2. sinon login à étapes ; 3. session ouverte => accueil (habilitations).
// La session vit en mémoire seulement (lib/session), jamais en storage navigateur.
export function App() {
  const [gate, setGate] = useState<Gate>('loading')
  const [session, setSession] = useState<TokenResult | null>(null)

  useEffect(() => {
    let alive = true
    bootstrapStatus().then(
      (r) => alive && setGate(r.required ? 'bootstrap' : 'login'),
      // Statut injoignable : on présente le login (le serveur refusera de toute façon).
      () => alive && setGate('login'),
    )
    return () => {
      alive = false
    }
  }, [])

  const onAuthenticated = (t: TokenResult) => {
    storeSession(t)
    setSession(t)
  }
  const onLogout = () => {
    clearSession()
    setSession(null)
  }

  if (gate === 'loading') return <div className="min-h-screen bg-night" aria-busy="true" />
  if (gate === 'bootstrap') return <BootstrapPage onDone={() => setGate('login')} />
  if (!session) return <LoginPage onAuthenticated={onAuthenticated} />
  return <HomePage session={session} onLogout={onLogout} />
}
