import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import { api, setUnauthorizedHandler } from '../api'
import { decodeJwtExp, tokenStore } from '../api/tokenStore'
import { AuthContext, type AuthContextValue } from '../hooks/auth-context'

function validStoredToken(): string | null {
  const t = tokenStore.get()
  if (!t) return null
  const exp = decodeJwtExp(t)
  if (exp !== null && exp * 1000 <= Date.now()) {
    tokenStore.clear()
    return null
  }
  return t
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(validStoredToken)

  const logout = useCallback(() => {
    tokenStore.clear()
    setToken(null)
  }, [])

  const login = useCallback(async (username: string, password: string) => {
    const res = await api.login({ username, password })
    tokenStore.set(res.accessToken)
    setToken(res.accessToken)
  }, [])

  // 401 sur une requête authentifiée => retour au login.
  useEffect(() => {
    setUnauthorizedHandler(logout)
    return () => setUnauthorizedHandler(null)
  }, [logout])

  // Déconnexion automatique à l'expiration du JWT (15 min).
  useEffect(() => {
    if (!token) return
    const exp = decodeJwtExp(token)
    if (exp === null) return
    const delay = Math.max(0, exp * 1000 - Date.now())
    const id = setTimeout(logout, Math.min(delay, 2 ** 31 - 1))
    return () => clearTimeout(id)
  }, [token, logout])

  const value = useMemo<AuthContextValue>(
    () => ({ isAuthenticated: token !== null, login, logout }),
    [token, login, logout],
  )
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
