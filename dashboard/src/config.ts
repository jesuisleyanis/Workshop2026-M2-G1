const trim = (s: string) => s.replace(/\/+$/, '')

/** Base du moteur de remédiation (jamais appelée directement par le navigateur en prod). */
export const REMEDIATION_BASE: string = trim(import.meta.env.VITE_REMEDIATION_BASE ?? '/remediation')

/** GET <base>/stream - flux SSE temps réel. */
export const STREAM_URL = `${REMEDIATION_BASE}/stream`

/** UI de l'assistant RAG (iframe). Slash final requis : l'UI utilise des chemins relatifs. */
export const ASSISTANT_URL: string = import.meta.env.VITE_ASSISTANT_URL ?? '/assistant/'

/** API de l'assistant (summarize / postmortem / propose), même proxy que l'iframe. */
export const ASSISTANT_API = `${trim(ASSISTANT_URL)}/api/v1`

/** POST - action manuelle confirmée par l'opérateur (jeton injecté par nginx). */
export const MANUAL_ACTIONS_URL = `${REMEDIATION_BASE}/manual-actions`

export const GRAFANA_BASE: string = trim(import.meta.env.VITE_GRAFANA_BASE ?? 'http://localhost:3000')

/**
 * Score ML et santé des services : le moteur n'émet ni `score` ni `health`. Ils sont lus dans
 * Prometheus (`resilience_anomaly_score`, `up`) via le proxy nginx en lecture seule
 * `/prometheus/api/v1/query` (same-origin : la CSP `connect-src 'self'` reste valable).
 * Chaîne vide = polling désactivé.
 */
export const PROMETHEUS_BASE: string = trim(import.meta.env.VITE_PROMETHEUS_BASE ?? '/prometheus')
export const METRICS_POLL_MS: number = Number(import.meta.env.VITE_METRICS_POLL_MS ?? 2000) || 2000

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
 * En prod, nginx ne publie que /remediation/stream et POST /remediation/manual-actions :
 * les attaques partent du PC Attaquant.
 */
export const LIVE_TRIGGERS: boolean = import.meta.env.DEV || import.meta.env.VITE_LIVE_TRIGGERS === 'true'
export const TRIGGER_URL = `${REMEDIATION_BASE}/trigger`
