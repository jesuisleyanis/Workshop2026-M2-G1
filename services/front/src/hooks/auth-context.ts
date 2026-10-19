import { createContext } from 'react'

export type LogoutReason = 'manual' | 'expired'

export interface AuthContextValue {
  isAuthenticated: boolean
  /** Identifiant saisi au login (affichage uniquement). */
  username: string | null
  /** Expiration du JWT (ms epoch), lue dans le claim `exp` ou `expires_in`. */
  expiresAt: number | null
  /** Message d'information affiché sur la page de connexion (déconnexion, expiration). */
  notice: string | null
  login: (username: string, password: string) => Promise<void>
  logout: (reason?: LogoutReason) => void
}

export const AuthContext = createContext<AuthContextValue | null>(null)
