import { useEffect, useState } from 'react'
import { LoginPage } from './pages/LoginPage'
import { bootstrapStatus, type TokenResult } from './api/auth'
import { clearSession, setSession as storeSession } from './lib/session'
import { Brand } from './components/Brand'

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

// --- Placeholders (T9 : remplacés par pages/BootstrapPage et pages/HomePage) ------------------

/** T9 : `import { BootstrapPage } from './pages/BootstrapPage'` (enrôlement du premier admin). */
function BootstrapPage({ onDone }: { onDone: () => void }) {
  return (
    <div data-testid="bootstrap-page" className="grid min-h-screen place-items-center bg-white p-6">
      <div className="flex w-full max-w-[380px] flex-col gap-4">
        <Brand />
        <h1 className="text-[30px] font-semibold tracking-[-0.03em]">Premier administrateur</h1>
        <p className="text-[15px] text-ink-3">Aucun administrateur n’est enrôlé. Écran de création à venir.</p>
        <button type="button" className="btn-ghost" onClick={onDone}>
          Aller à la connexion
        </button>
      </div>
    </div>
  )
}

/** T9 : `import { HomePage } from './pages/HomePage'` (accueil + habilitations). */
function HomePage({ session, onLogout }: { session: TokenResult; onLogout: () => void }) {
  return (
    <div data-testid="home-page" className="mx-auto flex min-h-screen w-full max-w-[560px] flex-col gap-6 p-6">
      <header className="flex items-center justify-between">
        <Brand />
        <button type="button" onClick={onLogout} className="btn-ghost">
          Se déconnecter
        </button>
      </header>
      <div className="rounded-xl bg-ok-bg px-4 py-3 text-sm text-ok-fg" role="status">
        Accès autorisé — rôle « {session.role} ».
      </div>
    </div>
  )
}
