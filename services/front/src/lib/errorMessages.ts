import { ApiError } from '../api/errors'

const BY_CODE: Record<string, string> = {
  insufficient_funds: 'Solde insuffisant pour ce virement.',
  limit_exceeded: 'Plafond mensuel de virement atteint.',
  invalid_credentials: 'Identifiant ou mot de passe incorrect.',
  validation_error: 'Les informations saisies sont invalides.',
  rate_limited: 'Trop de tentatives. Patientez un instant avant de réessayer.',
}

/** Message affichable à l'utilisateur pour une erreur d'API (jamais de détail technique brut). */
export function userMessage(err: unknown): string {
  if (!(err instanceof ApiError)) return 'Une erreur inattendue est survenue.'
  if (err.isNetwork) return err.message
  if (err.isRateLimited) return BY_CODE.rate_limited!
  return BY_CODE[err.code] ?? err.message
}
