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

interface JwtClaims {
  sub: string | null
  exp: number | null
}

/** Lit les claims `sub` (username) et `exp` (secondes epoch) d'un JWT sans le vérifier (la vérification est côté serveur). */
export function decodeJwtClaims(token: string): JwtClaims {
  const part = token.split('.')[1]
  if (!part) return { sub: null, exp: null }
  try {
    const b64 = part.replace(/-/g, '+').replace(/_/g, '/')
    const json = atob(b64.padEnd(Math.ceil(b64.length / 4) * 4, '='))
    const payload = JSON.parse(json) as { sub?: unknown; exp?: unknown }
    return {
      sub: typeof payload.sub === 'string' ? payload.sub : null,
      exp: typeof payload.exp === 'number' ? payload.exp : null,
    }
  } catch {
    return { sub: null, exp: null }
  }
}

export function decodeJwtExp(token: string): number | null {
  return decodeJwtClaims(token).exp
}
