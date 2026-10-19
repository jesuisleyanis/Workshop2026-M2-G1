import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import { api, setUnauthorizedHandler } from '../api'
import { decodeJwtClaims, tokenStore } from '../api/tokenStore'
import { AuthContext, type AuthContextValue, type LogoutReason } from '../hooks/auth-context'

interface Session {
  token: string
  username: string | null
  expiresAt: number | null
}

const NOTICES: Record<LogoutReason, string> = {
  manual: 'Vous êtes déconnecté.',
  expired: 'Votre session a expiré. Reconnectez-vous pour continuer.',
}

/** Session depuis le JWT : `sub` = identifiant (service auth), `exp` = expiration. */
function sessionFrom(token: string, fallbackUser: string | null = null, expiresIn: number | null = null): Session {
  const { sub, exp } = decodeJwtClaims(token)
  const expiresAt = exp !== null ? exp * 1000 : expiresIn !== null ? Date.now() + expiresIn * 1000 : null
  return { token, username: sub ?? fallbackUser, expiresAt }
}

function storedSession(): Session | null {
  const token = tokenStore.get()
  if (!token) return null
  const session = sessionFrom(token)
  if (session.expiresAt !== null && session.expiresAt <= Date.now()) {
    tokenStore.clear()
    return null
  }
  return session
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(storedSession)
  const [notice, setNotice] = useState<string | null>(null)

  const logout = useCallback((reason: LogoutReason = 'manual') => {
    tokenStore.clear()
    setSession(null)
    setNotice(NOTICES[reason])
  }, [])

  const login = useCallback(async (username: string, password: string) => {
    const res = await api.login({ username, password })
    tokenStore.set(res.accessToken)
    setNotice(null)
    setSession(sessionFrom(res.accessToken, username, res.expiresIn))
  }, [])

  // 401 sur une requête authentifiée => retour au login.
  useEffect(() => {
    setUnauthorizedHandler(() => logout('expired'))
    return () => setUnauthorizedHandler(null)
  }, [logout])

  // Déconnexion proactive à l'expiration du JWT (15 min) ; le 401 serveur reste le filet de sécurité.
  const expiresAt = session?.expiresAt ?? null
  useEffect(() => {
    if (expiresAt === null) return
    const delay = Math.max(0, expiresAt - Date.now())
    const id = setTimeout(() => logout('expired'), Math.min(delay, 2 ** 31 - 1))
    return () => clearTimeout(id)
  }, [expiresAt, logout])

  const value = useMemo<AuthContextValue>(
    () => ({
      isAuthenticated: session !== null,
      username: session?.username ?? null,
      expiresAt,
      notice,
      login,
      logout,
    }),
    [session, expiresAt, notice, login, logout],
  )
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
