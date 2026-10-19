import { useEffect, useState } from 'react'
import { Link, NavLink, Outlet, useLocation } from 'react-router-dom'
import { useAuth } from '../hooks/useAuth'
import { BankDataProvider } from './BankDataProvider'
import { Brand } from './ui'

const NAV = [
  { to: '/', label: 'Accueil', kicker: '', title: "Vue d'ensemble" },
  { to: '/accounts', label: 'Comptes', kicker: 'Vos comptes', title: 'Comptes' },
  { to: '/transfer', label: 'Virement', kicker: 'Émettre un virement', title: 'Nouveau virement' },
  { to: '/history', label: 'Historique', kicker: 'Toutes vos opérations', title: 'Historique' },
] as const

export function Layout() {
  const { username, expiresAt, logout } = useAuth()
  const { pathname } = useLocation()
  const page = NAV.find((n) => n.to === pathname) ?? NAV[0]
  const kicker = page.to === '/' ? `Bonjour ${username ?? ''}`.trim() : page.kicker

  return (
    <BankDataProvider>
      <div className="flex min-h-screen flex-wrap gap-3.5 bg-frame p-3.5">
        <aside className="flex max-w-[250px] flex-[1_1_200px] flex-col gap-6 px-2.5 py-3.5">
          <div className="px-2">
            <Brand />
          </div>
          <nav aria-label="Navigation principale" className="flex flex-col gap-1">
            {NAV.map((n) => (
              <NavLink
                key={n.to}
                to={n.to}
                end
                className={({ isActive }) =>
                  `group flex h-[46px] items-center justify-between rounded-[13px] px-3.5 text-[15px] font-medium ${isActive ? 'bg-night text-white' : 'text-[#3a3d44] hover:bg-page'}`
                }
              >
                {n.label}
                <span className="h-1.5 w-1.5 rounded-full group-aria-[current=page]:bg-white" aria-hidden />
              </NavLink>
            ))}
          </nav>
          <div className="flex-1" />
          <SessionCard username={username} expiresAt={expiresAt} onLogout={() => logout('manual')} />
        </aside>

        <main className="flex min-w-0 flex-[999_1_560px] flex-col gap-7 rounded-[22px] bg-white p-[clamp(18px,3vw,36px)]">
          <header className="flex flex-wrap items-end justify-between gap-4">
            <div className="flex flex-col gap-1">
              {kicker && <span className="text-sm text-ink-3">{kicker}</span>}
              <h1 className="text-[clamp(26px,3vw,34px)] font-semibold tracking-[-0.035em]">{page.title}</h1>
            </div>
            {page.to !== '/transfer' && (
              <Link to="/transfer" className="btn-primary">
                Nouveau virement
              </Link>
            )}
          </header>
          <Outlet />
        </main>
      </div>
    </BankDataProvider>
  )
}

function SessionCard({ username, expiresAt, onLogout }: { username: string | null; expiresAt: number | null; onLogout: () => void }) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (expiresAt === null) return
    const id = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(id)
  }, [expiresAt])
  const left = expiresAt === null ? null : Math.max(0, Math.round((expiresAt - now) / 1000))
  const name = username ?? 'Client'

  return (
    <div className="flex flex-col gap-3 rounded-2xl bg-white p-3.5">
      <div className="flex items-center gap-2.5">
        <div className="grid h-9 w-9 place-items-center rounded-full bg-page text-[13px] font-semibold" aria-hidden>
          {name.slice(0, 2).toUpperCase()}
        </div>
        <div className="flex min-w-0 flex-col">
          <span className="truncate text-sm font-semibold">{name}</span>
          {left !== null && (
            <span className={`font-mono text-[11px] ${left < 120 ? 'text-[#b26b00]' : 'text-ink-3'}`}>
              Session {Math.floor(left / 60)}:{String(left % 60).padStart(2, '0')}
            </span>
          )}
        </div>
      </div>
      <button type="button" className="btn-ghost h-10" onClick={onLogout}>
        Se déconnecter
      </button>
    </div>
  )
}
