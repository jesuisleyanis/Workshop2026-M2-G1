const trim = (s: string) => s.replace(/\/+$/, '')

/** Base du moteur de remédiation (jamais appelée directement par le navigateur en prod). */
export const REMEDIATION_BASE: string = trim(import.meta.env.VITE_REMEDIATION_BASE ?? '/remediation')

/** GET <base>/stream - flux SSE temps réel. */
export const STREAM_URL = `${REMEDIATION_BASE}/stream`

export const GRAFANA_BASE: string = trim(import.meta.env.VITE_GRAFANA_BASE ?? 'http://localhost:3000')
