import { useState } from 'react'
import { LoginPage } from './pages/LoginPage'
import type { TokenResult } from './api/auth'

// Coquille du back-office : tant qu'aucune session n'est ouverte, on montre le login à étapes.
// L'écran d'habilitations (enrôlement des visages + rôles) est le lot L6 — placeholder ici.
export function App() {
  const [session, setSession] = useState<TokenResult | null>(null)
  if (!session) return <LoginPage onAuthenticated={setSession} />
  return <Home role={session.role} onLogout={() => setSession(null)} />
}

function Home({ role, onLogout }: { role: string; onLogout: () => void }) {
  return (
    <div className="mx-auto flex min-h-screen w-full max-w-[560px] flex-col gap-6 p-6">
      <header className="flex items-center justify-between">
        <div>
          <p className="text-sm font-semibold text-ink-3">RESILIENCE-ALPHA</p>
          <h1 className="text-[24px] font-semibold tracking-[-0.03em]">Back-office</h1>
        </div>
        <button
          type="button"
          onClick={onLogout}
          className="h-10 cursor-pointer rounded-xl border-[1.5px] border-line px-4 text-sm font-semibold"
        >
          Se déconnecter
        </button>
      </header>
      <div className="rounded-xl bg-ok-bg px-4 py-3 text-sm text-ok-fg" role="status">
        Accès autorisé — rôle « {role} ».
      </div>
      <section className="rounded-2xl border border-line bg-frame p-5">
        <h2 className="text-[17px] font-semibold">Gestion des habilitations</h2>
        <p className="mt-1 text-sm text-ink-3">
          Enrôlement des visages et gestion des rôles — à venir (lot L6).
        </p>
      </section>
    </div>
  )
}
