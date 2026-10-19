const trim = (s: string) => s.replace(/\/+$/, '')

/** Base du moteur de remédiation (jamais appelée directement par le navigateur en prod). */
export const REMEDIATION_BASE: string = trim(import.meta.env.VITE_REMEDIATION_BASE ?? '/remediation')

/** GET <base>/stream - flux SSE temps réel. */
export const STREAM_URL = `${REMEDIATION_BASE}/stream`

export const GRAFANA_BASE: string = trim(import.meta.env.VITE_GRAFANA_BASE ?? 'http://localhost:3000')

/**
 * Source des événements :
 *  - live       : flux SSE réel uniquement (défaut, démo jury) ;
 *  - auto       : flux réel, bascule en simulation locale s'il n'a jamais pu s'ouvrir ;
 *  - simulation : simulation locale d'emblée (répétition sans stack).
 */
export type StreamSource = 'live' | 'auto' | 'simulation'
const rawSource = import.meta.env.VITE_STREAM_SOURCE
export const STREAM_SOURCE: StreamSource = rawSource === 'auto' || rawSource === 'simulation' ? rawSource : 'live'

/**
 * Déclencheurs d'incident en flux réel : dev uniquement (`npm run mock` expose GET /trigger).
 * En prod, nginx ne publie que /remediation/stream : les attaques partent du PC Attaquant.
 */
export const LIVE_TRIGGERS: boolean = import.meta.env.DEV || import.meta.env.VITE_LIVE_TRIGGERS === 'true'
export const TRIGGER_URL = `${REMEDIATION_BASE}/trigger`
