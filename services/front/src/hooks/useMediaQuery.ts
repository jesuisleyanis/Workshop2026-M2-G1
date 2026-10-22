import { useCallback, useSyncExternalStore } from 'react'

/** Point de rupture desktop des maquettes (barre latérale) ; en dessous : shell mobile (barre d'onglets). */
export const DESKTOP_QUERY = '(min-width: 1024px)'

export function useMediaQuery(query: string): boolean {
  const subscribe = useCallback(
    (onChange: () => void) => {
      if (typeof window.matchMedia !== 'function') return () => {}
      const mql = window.matchMedia(query)
      mql.addEventListener('change', onChange)
      return () => mql.removeEventListener('change', onChange)
    },
    [query],
  )
  return useSyncExternalStore(subscribe, () => typeof window.matchMedia === 'function' && window.matchMedia(query).matches)
}

export const useIsDesktop = () => useMediaQuery(DESKTOP_QUERY)
