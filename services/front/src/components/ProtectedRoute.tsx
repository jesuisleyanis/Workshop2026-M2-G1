import { Navigate, Outlet, useLocation } from 'react-router-dom'
import { useAuth } from '../hooks/useAuth'

export interface LoginRedirectState {
  from?: string
}

export function ProtectedRoute() {
  const { isAuthenticated } = useAuth()
  const location = useLocation()
  if (isAuthenticated) return <Outlet />
  // Chemin ET paramètres : /statements/print?account=… doit survivre à une reconnexion.
  const state: LoginRedirectState = { from: location.pathname + location.search }
  return <Navigate to="/login" replace state={state} />
}
