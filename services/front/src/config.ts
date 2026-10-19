/** Configuration runtime (valeurs injectées au build par Vite). */
const raw = import.meta.env.VITE_API_BASE ?? ''

/** Base d'URL de l'API sans slash final. Vide = same-origin (derrière le WAF). */
export const API_BASE: string = raw.replace(/\/+$/, '')
