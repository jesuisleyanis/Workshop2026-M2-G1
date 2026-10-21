import { createContext, useContext, useEffect } from 'react'

export interface Shell {
  isDesktop: boolean
  /** Message éphémère en bas d'écran (copie, téléchargement…). */
  toast: (message: string) => void
  /** Remplace l'action du bouton Retour de l'en-tête (ex. étapes de l'assistant d'envoi) ; null = défaut. */
  setBackOverride: (fn: (() => void) | null) => void
}

export const ShellContext = createContext<Shell | null>(null)

export function useShell(): Shell {
  const ctx = useContext(ShellContext)
  if (!ctx) throw new Error('useShell doit être utilisé dans <Layout>')
  return ctx
}

/** Branche un retour personnalisé tant que `fn` est non nul. */
export function useBackOverride(fn: (() => void) | null): void {
  const { setBackOverride } = useShell()
  useEffect(() => {
    setBackOverride(fn)
    return () => setBackOverride(null)
  }, [fn, setBackOverride])
}
