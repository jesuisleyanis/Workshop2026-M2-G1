/**
 * Jeton OPÉRATEUR du moteur de remédiation (REMEDIATION_OPERATOR_TOKEN).
 *
 * Les écritures déclenchées par un humain depuis le dashboard (déblocage d'IP) l'exigent ; le nginx du
 * dashboard ne l'injecte jamais (il ne le connaît pas) et se contente de relayer l'en-tête Authorization.
 * Saisi par l'opérateur au premier usage, gardé en sessionStorage UNIQUEMENT (onglet courant, effacé à
 * la fermeture), jamais dans le bundle ni en localStorage, effacé dès que le moteur le refuse (401/403).
 * Il n'est envoyé que sur les écritures : les lectures passent par le jeton de service injecté par nginx.
 */
export const OPERATOR_TOKEN_KEY = 'resilience.operatorToken'

export function readOperatorToken(): string | null {
  try {
    return sessionStorage.getItem(OPERATOR_TOKEN_KEY) || null
  } catch {
    return null // stockage indisponible (navigation privée stricte) : redemandé à chaque usage
  }
}

export function saveOperatorToken(token: string): void {
  try {
    sessionStorage.setItem(OPERATOR_TOKEN_KEY, token)
  } catch {
    /* sans stockage, le jeton sert pour cette seule requête */
  }
}

export function clearOperatorToken(): void {
  try {
    sessionStorage.removeItem(OPERATOR_TOKEN_KEY)
  } catch {
    /* rien à effacer */
  }
}

export function operatorAuthHeader(token: string): Record<string, string> {
  return { Authorization: `Bearer ${token}` }
}

export type OperatorOutcome = 'ok' | 'unauthorized' | 'forbidden' | 'unavailable' | 'error'

/** Statut HTTP d'une écriture -> issue. 401/403 effacent le jeton mémorisé : il sera redemandé. */
export function operatorOutcome(status: number): OperatorOutcome {
  if (status >= 200 && status < 300) return 'ok'
  if (status === 401 || status === 403) {
    clearOperatorToken()
    return status === 401 ? 'unauthorized' : 'forbidden'
  }
  return status === 503 ? 'unavailable' : 'error'
}

/** Message affiché à l'opérateur pour une issue en échec. */
export function operatorErrorMessage(outcome: Exclude<OperatorOutcome, 'ok'>, what: string): string {
  switch (outcome) {
    case 'unauthorized':
      return `${what} refusé (401) : jeton opérateur absent ou invalide. Il a été oublié : ressaisissez-le (clé REMEDIATION_OPERATOR_TOKEN du .env).`
    case 'forbidden':
      return `${what} refusé (403) : ce jeton n'est pas le jeton opérateur (REMEDIATION_OPERATOR_TOKEN, distinct du jeton de service).`
    case 'unavailable':
      return `${what} impossible (503) : actions opérateur désactivées côté moteur (REMEDIATION_OPERATOR_TOKEN non configuré).`
    default:
      return `Échec : ${what.toLowerCase()} (moteur injoignable ?) — réessayer.`
  }
}
