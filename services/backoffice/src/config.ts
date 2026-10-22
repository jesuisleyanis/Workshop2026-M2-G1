/** Base d'URL de l'API auth, sans slash final. Vide = same-origin (derrière le WAF). */
const raw = import.meta.env.VITE_API_BASE ?? ''
export const API_BASE: string = raw.replace(/\/+$/, '')
