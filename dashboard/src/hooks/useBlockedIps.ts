import { useEffect, useState } from 'react'
import { parseBlockedIps, type BlockedIp } from '../lib/blocklist'
import type { FetchLike } from './usePrometheusPolling'

export interface BlockedIpsState {
  /** null tant qu'aucune réponse valide n'est arrivée. */
  items: BlockedIp[] | null
  /** Dernière tentative en échec (moteur injoignable, réponse invalide). */
  error: boolean
}

const defaultFetch: FetchLike = (url) => fetch(url, { headers: { Accept: 'application/json' } })

/**
 * Relève la liste noire du WAF toutes les `intervalMs` via le proxy same-origin du dashboard.
 * Une erreur garde la dernière liste connue (pas de clignotement) et réessaie au tour suivant.
 */
export function useBlockedIps(url: string | null, intervalMs = 3000, fetchImpl: FetchLike = defaultFetch): BlockedIpsState {
  const [state, setState] = useState<BlockedIpsState>({ items: null, error: false })

  useEffect(() => {
    if (!url) return
    let stopped = false
    const tick = async () => {
      let items: BlockedIp[] | null = null
      try {
        const r = await fetchImpl(url)
        items = r.ok ? parseBlockedIps(await r.json()) : null
      } catch {
        items = null
      }
      if (stopped) return
      setState((prev) => (items ? { items, error: false } : { items: prev.items, error: true }))
    }
    void tick()
    const timer = setInterval(() => void tick(), intervalMs)
    return () => {
      stopped = true
      clearInterval(timer)
    }
  }, [url, intervalMs, fetchImpl])

  return state
}
