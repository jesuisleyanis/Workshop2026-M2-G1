import { useEffect, useState } from 'react'

/** Durée de vie du JWT (auth : 15 min). */
export const SESSION_S = 900

/** Secondes restantes avant `expiresAt` (ms epoch), rafraîchies chaque seconde. */
export function useSecondsLeft(expiresAt: number | null): number | null {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (expiresAt === null) return
    const id = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(id)
  }, [expiresAt])
  return expiresAt === null ? null : Math.max(0, Math.round((expiresAt - now) / 1000))
}

export const formatClock = (s: number) => `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`
export const sessionPct = (s: number) => `${Math.min(100, Math.round((s / SESSION_S) * 100))}%`
