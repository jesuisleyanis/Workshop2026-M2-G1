/**
 * État du service vu par le client (ticket #42, maquette D6) : « perturbé » dès qu'une requête
 * échoue côté serveur (réseau, timeout, 5xx), « rétabli » à la première réponse saine, puis masqué.
 * Le jury voit ainsi, côté client, l'attaque puis la reprise automatique — sans action humaine.
 */
export type ServiceState = 'ok' | 'degraded' | 'restored'

export const RESTORED_VISIBLE_MS = 4000

export function createServiceStatus(restoredMs = RESTORED_VISIBLE_MS, now: () => number = () => performance.now()) {
  let state: ServiceState = 'ok'
  let failedAt = -Infinity
  let timer: ReturnType<typeof setTimeout> | null = null
  const listeners = new Set<() => void>()

  function set(next: ServiceState) {
    if (next === state) return
    state = next
    listeners.forEach((l) => l())
  }

  return {
    get: () => state,
    subscribe(listener: () => void) {
      listeners.add(listener)
      return () => listeners.delete(listener)
    },
    /**
     * `startedAt` : instant de départ de la requête (même horloge que `now`). Une réponse saine d'une
     * requête partie avant la dernière panne (requêtes parallèles) ne prouve pas la reprise : ignorée.
     */
    report(up: boolean, startedAt = Infinity) {
      if (!up) {
        if (timer) clearTimeout(timer)
        timer = null
        failedAt = now()
        set('degraded')
      } else if (state === 'degraded' && startedAt > failedAt) {
        set('restored')
        timer = setTimeout(() => {
          timer = null
          set('ok')
        }, restoredMs)
      }
    },
    reset() {
      if (timer) clearTimeout(timer)
      timer = null
      failedAt = -Infinity
      set('ok')
    },
  }
}

export type ServiceStatus = ReturnType<typeof createServiceStatus>

export const serviceStatus = createServiceStatus()
