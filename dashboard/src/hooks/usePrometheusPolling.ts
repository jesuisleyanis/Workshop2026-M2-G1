import { useEffect, useRef } from 'react'
import { healthMessage, queryUrl, scoreMessages, SCORE_QUERY, UP_QUERY } from '../lib/prometheus'
import type { StreamMessage } from '../types/events'

export type FetchLike = (url: string) => Promise<{ ok: boolean; json(): Promise<unknown> }>

// Constante de module : une fonction par défaut créée à chaque rendu changerait les deps de
// l'effet et relancerait le polling en boucle (chaque message -> rendu -> nouvel effet).
const defaultFetch: FetchLike = (url) => fetch(url, { headers: { Accept: 'application/json' } })

/**
 * Interroge Prometheus (via le proxy same-origin du dashboard) toutes les `intervalMs` et
 * émet les messages `score` / `health` dans le même réducteur que le flux SSE.
 * Une erreur réseau n'interrompt pas le polling (la tentative suivante repart).
 */
export function usePrometheusPolling(
  base: string | null,
  onMessage: (m: StreamMessage) => void,
  intervalMs = 2000,
  fetchImpl: FetchLike = defaultFetch,
): void {
  const ref = useRef(onMessage)
  useEffect(() => {
    ref.current = onMessage
  })

  useEffect(() => {
    if (!base) return
    let stopped = false

    const query = async (q: string): Promise<unknown> => {
      const r = await fetchImpl(queryUrl(base, q))
      return r.ok ? r.json() : null
    }
    const tick = async () => {
      const [score, up] = await Promise.all([query(SCORE_QUERY).catch(() => null), query(UP_QUERY).catch(() => null)])
      if (stopped) return
      for (const m of scoreMessages(score)) ref.current(m)
      const h = healthMessage(up)
      if (h) ref.current(h)
    }

    void tick()
    const timer = setInterval(() => void tick(), intervalMs)
    return () => {
      stopped = true
      clearInterval(timer)
    }
  }, [base, intervalMs, fetchImpl])
}
