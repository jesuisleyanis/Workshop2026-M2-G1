import { useCallback, useEffect, useRef, useState } from 'react'
import { parseBlockedIps, type BlockedIp } from '../lib/blocklist'
import { operatorAuthHeader, operatorOutcome, type OperatorOutcome } from '../lib/operatorToken'

export interface BlockedIpsState {
  /** null tant qu'aucune réponse valide n'est arrivée. */
  items: BlockedIp[] | null
  /** Dernière tentative en échec (moteur injoignable, réponse invalide). */
  error: boolean
}

export interface BlockedIps extends BlockedIpsState {
  /**
   * Débloque une IP (bouton de la carte) avec le jeton OPÉRATEUR ; 'ok' si le moteur l'a retirée.
   * 401/403 effacent le jeton mémorisé. La liste est relue ensuite.
   */
  unblock: (ip: string, operatorToken: string) => Promise<OperatorOutcome>
}

type FetchFn = (
  url: string,
  init?: { method?: string; headers?: Record<string, string> },
) => Promise<{ ok: boolean; status?: number; json(): Promise<unknown> }>

const defaultFetch: FetchFn = (url, init) => fetch(url, { ...init, headers: { Accept: 'application/json', ...init?.headers } })

/**
 * Relève la liste noire du WAF toutes les `intervalMs` via le proxy same-origin du dashboard.
 * Une erreur garde la dernière liste connue (pas de clignotement) et réessaie au tour suivant.
 * `unblock` : DELETE <url>/<ip> avec l'en-tête X-Resilience-Dashboard exigé par nginx (anti-CSRF) et le
 * jeton OPÉRATEUR en Authorization (relayé tel quel par nginx, qui n'injecte rien sur les écritures).
 */
export function useBlockedIps(url: string | null, intervalMs = 3000, fetchImpl: FetchFn = defaultFetch): BlockedIps {
  const [state, setState] = useState<BlockedIpsState>({ items: null, error: false })
  const tickRef = useRef<() => Promise<void>>(async () => {})

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
    tickRef.current = tick
    void tick()
    const timer = setInterval(() => void tick(), intervalMs)
    return () => {
      stopped = true
      clearInterval(timer)
    }
  }, [url, intervalMs, fetchImpl])

  const unblock = useCallback(
    async (ip: string, operatorToken: string): Promise<OperatorOutcome> => {
      if (!url) return 'error'
      const headers = { 'X-Resilience-Dashboard': '1', ...operatorAuthHeader(operatorToken) }
      const outcome = await fetchImpl(`${url}/${ip}`, { method: 'DELETE', headers }).then(
        (r) => operatorOutcome(r.status ?? (r.ok ? 200 : 500)),
        (): OperatorOutcome => 'error',
      )
      await tickRef.current() // relecture immédiate : la carte reflète le WAF, pas l'intention
      return outcome
    },
    [url, fetchImpl],
  )

  return { ...state, unblock }
}
