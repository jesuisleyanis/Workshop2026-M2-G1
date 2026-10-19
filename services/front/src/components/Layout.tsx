import { NavLink, Outlet } from 'react-router-dom'
import { useAuth } from '../hooks/useAuth'

const link = ({ isActive }: { isActive: boolean }) =>
  `rounded-md px-3 py-2 text-sm font-medium ${isActive ? 'bg-teal-700 text-white' : 'text-slate-700 hover:bg-slate-200'}`

export function Layout() {
  const { logout } = useAuth()
  return (
    <div className="min-h-screen bg-slate-100">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-4xl items-center justify-between gap-4 px-4 py-3">
          <span className="font-semibold text-teal-800">Banque Résilience <span className="text-xs font-normal text-slate-500">(démo fictive)</span></span>
          <nav aria-label="Navigation principale" className="flex gap-1">
            <NavLink to="/" end className={link}>Tableau de bord</NavLink>
            <NavLink to="/transfer" className={link}>Virement</NavLink>
            <NavLink to="/history" className={link}>Historique</NavLink>
          </nav>
          <button type="button" onClick={logout} className="rounded-md border border-slate-300 px-3 py-1.5 text-sm hover:bg-slate-100">
            Déconnexion
          </button>
        </div>
      </header>
      <main className="mx-auto max-w-4xl px-4 py-8">
        <Outlet />
      </main>
    </div>
  )
}
