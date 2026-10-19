import { Navigate, Outlet, useLocation } from 'react-router-dom'
import { useAuth } from '../hooks/useAuth'

export interface LoginRedirectState {
  from?: string
}

export function ProtectedRoute() {
  const { isAuthenticated } = useAuth()
  const location = useLocation()
  if (isAuthenticated) return <Outlet />
  const state: LoginRedirectState = { from: location.pathname }
  return <Navigate to="/login" replace state={state} />
}
