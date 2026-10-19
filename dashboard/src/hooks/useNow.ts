import { useEffect, useState } from 'react'

/** Horloge qui se met à jour toutes les `intervalMs` (compteur live du MTTR, heure du bandeau). */
export function useNow(intervalMs = 1000): number {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), intervalMs)
    return () => clearInterval(id)
  }, [intervalMs])
  return now
}
