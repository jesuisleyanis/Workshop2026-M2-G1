const KEY = 'resilience.jwt'

/**
 * Le JWT vit en sessionStorage (vidé à la fermeture de l'onglet, durée de vie token : 15 min).
 * Aucun secret n'est stocké en dur côté front.
 */
export const tokenStore = {
  get(): string | null {
    try {
      return sessionStorage.getItem(KEY)
    } catch {
      return null
    }
  },
  set(token: string): void {
    try {
      sessionStorage.setItem(KEY, token)
    } catch {
      /* stockage indisponible : session non persistée */
    }
  },
  clear(): void {
    try {
      sessionStorage.removeItem(KEY)
    } catch {
      /* ignore */
    }
  },
}

/** Lit le claim `exp` (secondes epoch) d'un JWT sans le vérifier (la vérification est côté serveur). */
export function decodeJwtExp(token: string): number | null {
  const part = token.split('.')[1]
  if (!part) return null
  try {
    const b64 = part.replace(/-/g, '+').replace(/_/g, '/')
    const json = atob(b64.padEnd(Math.ceil(b64.length / 4) * 4, '='))
    const payload = JSON.parse(json) as { exp?: unknown }
    return typeof payload.exp === 'number' ? payload.exp : null
  } catch {
    return null
  }
}
