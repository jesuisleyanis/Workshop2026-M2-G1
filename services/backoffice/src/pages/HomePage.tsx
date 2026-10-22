import type { TokenResult } from '../api/auth'
import { Brand } from '../components/Brand'
import { HabilitationsPage } from './HabilitationsPage'

// Accueil du back-office. Le rôle de la session ne sert qu'à choisir l'écran : le serveur reste
// l'autorité (les routes d'administration refusent tout jeton non admin).
const ROLE_LABELS: Record<string, string> = { admin: 'Administrateur', operator: 'Opérateur' }

export function HomePage({ session, onLogout }: { session: TokenResult; onLogout: () => void }) {
  const isAdmin = session.role === 'admin'
  return (
    <div data-testid="home-page" className="mx-auto flex min-h-screen w-full max-w-[1040px] flex-col gap-6 p-4 sm:p-6">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <Brand />
        <div className="flex items-center gap-3">
          <span className="rounded-md bg-ok-bg px-2 py-0.5 text-[12px] text-ok-fg">{ROLE_LABELS[session.role] ?? session.role}</span>
          <button type="button" onClick={onLogout} className="btn-ghost">
            Se déconnecter
          </button>
        </div>
      </header>

      {isAdmin ? (
        <HabilitationsPage token={session.access_token} onUnauthorized={onLogout} />
      ) : (
        <section aria-labelledby="op-title" className="flex max-w-[560px] flex-col gap-2 rounded-2xl border border-line bg-frame p-6">
          <h1 id="op-title" className="text-[22px] font-semibold tracking-[-0.02em]">
            Accès opérateur
          </h1>
          <p className="text-[15px] text-ink-3">
            Votre session est ouverte en lecture seule. La gestion des habilitations est réservée aux administrateurs.
          </p>
        </section>
      )}
    </div>
  )
}
