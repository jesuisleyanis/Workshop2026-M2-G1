// Session du back-office : jeton gardé en mémoire uniquement (jamais de localStorage/sessionStorage).
import type { TokenResult } from '../api/auth'

let current: TokenResult | null = null

export const getSession = (): TokenResult | null => current
export const setSession = (t: TokenResult): void => {
  current = t
}
export const clearSession = (): void => {
  current = null
}

/** Lit la claim `role` du payload d'un JWT (affichage uniquement : le serveur reste l'autorité). */
export function decodeRole(token: string): string | null {
  const part = token.split('.')[1]
  if (!part) return null
  try {
    const b64 = part.replace(/-/g, '+').replace(/_/g, '/')
    const json = decodeURIComponent(
      atob(b64.padEnd(Math.ceil(b64.length / 4) * 4, '='))
        .split('')
        .map((c) => '%' + c.charCodeAt(0).toString(16).padStart(2, '0'))
        .join(''),
    )
    const role = (JSON.parse(json) as { role?: unknown }).role
    return typeof role === 'string' ? role : null
  } catch {
    return null
  }
}
