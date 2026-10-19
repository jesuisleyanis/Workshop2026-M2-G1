// Types alignés sur docs/contracts.md (conventions d'API REST) et sur les routes /api/v1.
// Les corps de réponse métier (login, comptes, transactions) ne sont pas figés champ à champ
// par le contrat : voir CAHIER-DES-CHARGES.md du front, section "Hypothèses de schéma".

/** Corps d'erreur normalisé : { "error": { code, message, request_id } } */
export interface ApiErrorBody {
  error: { code: string; message: string; request_id?: string | null }
}

export interface LoginRequest {
  username: string
  password: string
}

export interface LoginResponse {
  /** JWT HS256 (Bearer), durée 15 min. */
  accessToken: string
  tokenType: string
  /** Durée de vie en secondes, si fournie. */
  expiresIn: number | null
}

export interface Account {
  id: string
  owner: string | null
  label: string | null
  /** IBAN fictif (`iban_fake` côté payment-api), affiché tel quel. */
  iban: string | null
  balance: number
  currency: string
}

/** `result` des métriques resilience_transactions_total : created | rejected. */
export type TransactionStatus = 'created' | 'rejected'

export interface Transaction {
  id: string
  fromAccount: string
  toAccount: string
  amount: number
  currency: string
  status: TransactionStatus
  label: string | null
  createdAt: string
}

export interface TransferRequest {
  from_account: string
  to_account: string
  amount: number
  currency?: string
  label?: string
}
