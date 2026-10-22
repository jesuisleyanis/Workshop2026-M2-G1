/** IP en liste noire du WAF (GET /remediation/waf/blocked-ips, lecture seule). */
export interface BlockedIp {
  ip: string
  /** Horodatage ISO du dernier blocage connu du journal ; null si ajoutée hors moteur. */
  blockedAt: string | null
  list: 'temporary' | 'permanent' | 'unknown'
  incidentId: string | null
  incidentType: string | null
}

type Obj = Record<string, unknown>
const isObj = (v: unknown): v is Obj => typeof v === 'object' && v !== null && !Array.isArray(v)
const str = (v: unknown): string | null => (typeof v === 'string' && v ? v : null)
// Une IP littérale (v4 ou v6) : jamais de texte libre affiché comme une adresse.
const IP_RX = /^(?:\d{1,3}(?:\.\d{1,3}){3}|[0-9a-fA-F:.]*:[0-9a-fA-F:.]*)$/

/** Réponse du moteur -> lignes affichables ; toute entrée invalide est écartée, jamais d'exception. */
export function parseBlockedIps(raw: unknown): BlockedIp[] | null {
  if (!isObj(raw) || !Array.isArray(raw.blocked)) return null
  const out: BlockedIp[] = []
  for (const e of raw.blocked) {
    if (!isObj(e)) continue
    const ip = str(e.ip)
    if (!ip || !IP_RX.test(ip)) continue
    const list = e.list === 'temporary' || e.list === 'permanent' ? e.list : 'unknown'
    out.push({ ip, blockedAt: str(e.blocked_at), list, incidentId: str(e.incident_id), incidentType: str(e.incident_type) })
  }
  return out
}
