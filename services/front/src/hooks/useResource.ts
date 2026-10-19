import { useCallback, useEffect, useState } from 'react'
import { ApiError } from '../api/errors'

interface Settled<T> {
  version: number
  data: T | null
  error: ApiError | null
}

export interface Resource<T> {
  data: T | null
  error: ApiError | null
  loading: boolean
  reload: () => void
}

/** Charge une ressource (état de chargement + erreur + rechargement). Annule la requête au démontage. */
export function useResource<T>(loader: (signal: AbortSignal) => Promise<T>): Resource<T> {
  const [version, setVersion] = useState(1)
  const [settled, setSettled] = useState<Settled<T>>({ version: 0, data: null, error: null })

  useEffect(() => {
    const controller = new AbortController()
    loader(controller.signal)
      .then((data) => setSettled({ version, data, error: null }))
      .catch((err: unknown) => {
        if (controller.signal.aborted) return
        const error =
          err instanceof ApiError ? err : new ApiError(0, 'unexpected', 'Erreur inattendue.')
        setSettled((prev) => ({ version, data: prev.data, error }))
      })
    return () => controller.abort()
  }, [loader, version])

  const reload = useCallback(() => setVersion((v) => v + 1), [])

  return { data: settled.data, error: settled.error, loading: settled.version !== version, reload }
}
